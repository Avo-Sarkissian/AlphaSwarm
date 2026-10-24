"""YFinanceMarketDataProvider: price, volume and fundamentals from yfinance.

Invariants:
- Never raises: any failure for a ticker, including yfinance's own errors on
  delisted or unknown symbols, becomes a ``fetch_failed`` MarketSlice
  (docs/DECISIONS.md#adr-provider-never-raise).
- Two guarded stages per ticker, each in ``asyncio.to_thread``, under one batch
  deadline; a stage-2 failure keeps the stage-1 price; quotes older than
  ``stale_after_hours`` are 'stale' (docs/DECISIONS.md#p38-d-06, #p38-d-09).
  No cache, no semaphore (called once per run, not per agent).
- Money values use ``Decimal(str(x))``; NaN and infinities become ``None``.
- Tickers pass through unchanged; callers normalise them.
- ``get_prices``, ``get_fundamentals`` and ``get_volume`` return the same full
  slice from one batch; callers use exactly one of them per run.
- Logs carry counts, never symbols.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import structlog
import yfinance as yf

from alphaswarm.ingestion.providers import _fetch_failed_market_slice
from alphaswarm.ingestion.types import Fundamentals, MarketSlice, StalenessState

_SOURCE = "yfinance"
DEFAULT_DEADLINE_S: Final = 20.0
DEFAULT_STALE_AFTER_HOURS: Final = 24.0

log = structlog.get_logger(component="ingestion")


def _decimal_or_none(value: object) -> Decimal | None:
    """Convert a yfinance numeric field to Decimal, or None if absent/invalid.

    Pitfall 5: Decimal(str(...)) — never Decimal(float) — to avoid binary-float
    rounding on money values.

    NaN/Inf guard (Gemini review): yfinance can return float('nan') for
    trailingPE on pre-earnings companies. Decimal(str(float('nan'))) produces
    Decimal('NaN'), not None, which would leak a NaN Decimal into downstream
    consumers. Guard here instead of at every call site.
    """
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return Decimal(str(value))


def _volume_or_none(raw: object) -> int | None:
    """last_volume can be NaN (e.g. pre-market); int(nan) raises, so NaN/Inf -> None."""
    if raw is None or (isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw))):
        return None
    volume: int = int(raw)  # type: ignore[call-overload]  # numpy ints are not int
    return volume


def _quote_time(value: object) -> datetime | None:
    """yfinance regularMarketTime (epoch seconds) as aware UTC, or None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def classify_quote(as_of: datetime | None, now: datetime, *, stale_after_hours: float) -> StalenessState:
    """'stale' when the quote is older than the window; 'fresh' otherwise or when unknown."""
    if as_of is None:
        return "fresh"
    return "stale" if (now - as_of).total_seconds() > stale_after_hours * 3600 else "fresh"


def _stage_price_sync(ticker: str) -> tuple[Decimal | None, int | None]:
    """Stage 1, in a worker thread: fast_info price and volume.

    Raises on any error: fast_info.last_price raises KeyError('currentTradingPeriod')
    on delisted tickers (Pitfall 1); the caller turns that into fetch_failed.
    """
    fast = yf.Ticker(ticker).fast_info
    return _decimal_or_none(fast.last_price), _volume_or_none(fast.last_volume)


def _stage_info_sync(ticker: str) -> tuple[Fundamentals, datetime | None]:
    """Stage 2, in a worker thread: fundamentals and the quote time from info (sync HTTP)."""
    info = yf.Ticker(ticker).info
    fundamentals = Fundamentals(
        pe_ratio=_decimal_or_none(info.get("trailingPE")),
        eps=_decimal_or_none(info.get("trailingEps")),
        market_cap=_decimal_or_none(info.get("marketCap")),
    )
    return fundamentals, _quote_time(info.get("regularMarketTime"))


@dataclass
class _Progress:
    """What one symbol's fetch produced so far; read after the deadline."""

    priced: bool = False
    price: Decimal | None = None
    volume: int | None = None
    fundamentals: Fundamentals | None = None
    as_of: datetime | None = None


class YFinanceMarketDataProvider:
    """Real MarketDataProvider backed by yfinance; never raises.

    All three Protocol methods share a single _fetch_batch_shared implementation
    because yfinance returns price, volume, and fundamentals per symbol and the
    caller requests prices once per run.

    Providers MAY accept an optional state_store via attach_audit_sink() to
    surface each fetch on the WS SignalWire ticker. The hook is dependency-free:
    passing None or never calling attach keeps behaviour identical.
    """

    def __init__(
        self,
        *,
        deadline_s: float = DEFAULT_DEADLINE_S,
        stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if deadline_s <= 0 or stale_after_hours <= 0:
            raise ValueError("deadline_s and stale_after_hours must be positive")
        self._deadline_s = deadline_s
        self._stale_after_hours = stale_after_hours
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        # Lazy-typed to avoid forcing alphaswarm.state import at module load.
        # Set via attach_audit_sink() once StateStore is available on app.state.
        self._audit_sink: object | None = None

    def attach_audit_sink(self, state_store: object) -> None:
        """Attach a StateStore-shaped object (`record_data_source` callable).

        The provider only calls `state_store.record_data_source(source, query,
        result, used)` — no other attribute. Decoupled this way so unit tests
        can pass any duck-typed sink. Lifespan wires this from
        alphaswarm.web.app after app_state is constructed.
        """
        self._audit_sink = state_store

    def _audit(self, query: str, result: str, used: bool) -> None:
        """Non-fatal audit shim — never raises into the fetch path."""
        sink = self._audit_sink
        if sink is None:
            return
        with contextlib.suppress(Exception):  # observability must never break the fetch
            sink.record_data_source(  # type: ignore[attr-defined]
                source="yfinance",
                query=query,
                result=result,
                used=used,
            )

    async def _fetch_stages(self, ticker: str, progress: _Progress) -> None:
        try:
            progress.price, progress.volume = await asyncio.to_thread(_stage_price_sync, ticker)
            progress.priced = True
        except Exception:  # noqa: BLE001 — never raise; a stage-1 failure is fetch_failed
            return
        with contextlib.suppress(Exception):  # keep the stage-1 price (docs/DECISIONS.md#p38-d-06)
            progress.fundamentals, progress.as_of = await asyncio.to_thread(_stage_info_sync, ticker)

    def _to_slice(self, ticker: str, progress: _Progress, now: datetime) -> MarketSlice:
        if not progress.priced:
            return _fetch_failed_market_slice(ticker, _SOURCE)
        return MarketSlice(
            ticker=ticker,
            price=progress.price,
            volume=progress.volume,
            fundamentals=progress.fundamentals,
            fetched_at=now,
            as_of=progress.as_of,
            source=_SOURCE,
            staleness=classify_quote(progress.as_of, now, stale_after_hours=self._stale_after_hours),
        )

    async def _fetch_batch_shared(self, tickers: list[str]) -> dict[str, MarketSlice]:
        if not tickers:  # Pitfall 9 — empty input starts no fetch
            return {}
        unique = list(dict.fromkeys(tickers))  # duplicates collapse (matches the fake)
        progress = {ticker: _Progress() for ticker in unique}
        try:
            async with asyncio.timeout(self._deadline_s):
                async with asyncio.TaskGroup() as group:
                    for ticker in unique:
                        group.create_task(self._fetch_stages(ticker, progress[ticker]))
        except TimeoutError:
            # Worker threads cannot be cancelled; their late results are dropped.
            log.warning(
                "market_fetch_deadline_exceeded",
                tickers=len(unique),
                priced=sum(1 for p in progress.values() if p.priced),
                deadline_s=self._deadline_s,
            )
        now = self._clock()
        slices = {ticker: self._to_slice(ticker, progress[ticker], now) for ticker in unique}
        # Audit one entry per ticker so the SignalWire ticker matches batch shape.
        for s in slices.values():
            ok = s.staleness != "fetch_failed"
            self._audit(
                query=f"{s.ticker} OHLCV",
                result="ok" if ok else "error: fetch_failed",
                used=True,
            )
        return slices

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)
