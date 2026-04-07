"""Async market data fetching with disk cache and graceful degradation (Phase 17)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import httpx
import structlog

from alphaswarm.types import ExtractedTicker, MarketDataSnapshot

logger = structlog.get_logger(component="market_data")

CACHE_DIR = Path("data/market_cache")
CACHE_TTL_SECONDS = 3600  # 1 hour per D-10

AV_BASE_URL = "https://www.alphavantage.co/query"

# Per-ticker locks to prevent concurrent yfinance access to same symbol (D-06, Pitfall 1)
_ticker_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# yfinance blocking fetch (run in thread pool via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _fetch_yfinance_sync(symbol: str) -> dict:  # type: ignore[return]
    """Blocking yfinance fetch — MUST be called via asyncio.to_thread().

    Returns a flat dict with price_history and all fundamental fields.
    Raises ValueError if yfinance returns empty info (treated as failure).
    """
    import yfinance as yf  # noqa: PLC0415 — import inside fn to avoid side effects in tests

    ticker = yf.Ticker(symbol)

    # Price history: 90 days OHLCV (D-01)
    hist = ticker.history(period="3mo")
    price_history = [
        {
            "date": row.Index.isoformat(),
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
            "volume": int(row.Volume),
        }
        for row in hist.itertuples()
    ]

    # Financial fundamentals from .info (D-02)
    info = ticker.info

    # Pitfall 2: .info silently returns {} on failure — check essential fields
    if info.get("marketCap") is None and info.get("trailingPE") is None:
        raise ValueError(f"yfinance returned empty info for {symbol}")

    data: dict = {
        "price_history": price_history,
        "pe_ratio": info.get("trailingPE"),
        "market_cap": info.get("marketCap"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "eps_trailing": info.get("trailingEps"),
        "revenue_ttm": info.get("totalRevenue"),
        "gross_margin_pct": info.get("grossMargins"),
        "debt_to_equity": info.get("debtToEquity"),
        "company_name": info.get("shortName", symbol),
        "earnings_surprise_pct": None,
        "next_earnings_date": None,
    }

    # Earnings dates — wrap in try/except (Pitfall 6: tz-aware index, can fail for some tickers)
    try:
        ed = ticker.earnings_dates
        if ed is not None and not ed.empty:
            # Most recent earnings surprise
            reported = ed[ed["Reported EPS"].notna()]
            if not reported.empty:
                latest = reported.iloc[0]
                data["earnings_surprise_pct"] = latest.get("Surprise(%)")

            # Next earnings date (future)
            import pandas as pd  # noqa: PLC0415

            now = pd.Timestamp.now(tz="America/New_York")
            future = ed[ed.index > now]
            if not future.empty:
                data["next_earnings_date"] = future.index[-1].isoformat()
    except Exception:  # noqa: BLE001
        pass  # earnings_dates can fail for some tickers

    # Compute summary stats from price_history
    if price_history:
        data["last_close"] = price_history[-1]["close"]
        closes = [row["close"] for row in price_history]
        # price_change_30d_pct: last 22 trading days (~1 month)
        if len(closes) >= 22:
            close_30d_ago = float(closes[-22])
            last = float(data["last_close"])
            data["price_change_30d_pct"] = (last - close_30d_ago) / close_30d_ago * 100
        else:
            data["price_change_30d_pct"] = None
        # price_change_90d_pct: first to last
        first_close = float(closes[0])
        last_close_val = float(data["last_close"])
        data["price_change_90d_pct"] = (
            (last_close_val - first_close) / first_close * 100 if first_close != 0 else None
        )
        # avg_volume_30d: average volume of last 22 entries
        recent_vols = [row["volume"] for row in price_history[-22:]]
        data["avg_volume_30d"] = sum(recent_vols) / len(recent_vols)
    else:
        data["last_close"] = None
        data["price_change_30d_pct"] = None
        data["price_change_90d_pct"] = None
        data["avg_volume_30d"] = None

    return data


# ---------------------------------------------------------------------------
# Alpha Vantage async fallback (D-08, D-17, D-18)
# ---------------------------------------------------------------------------


def _safe_float(val: object) -> float | None:
    """Convert AV string values to float; return None for missing/zero/dash values."""
    if val is None or val == "None" or val == "-" or val == "0":
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


async def _fetch_alpha_vantage(symbol: str, api_key: str) -> MarketDataSnapshot:
    """Fetch market data from Alpha Vantage as yfinance fallback (D-08, D-18).

    Calls GLOBAL_QUOTE (price) + OVERVIEW (fundamentals). Returns a
    MarketDataSnapshot with partial fundamentals (no gross_margin_pct or
    debt_to_equity — not provided by AV OVERVIEW).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        quote_resp = await client.get(
            AV_BASE_URL,
            params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key},
        )
        quote_data = quote_resp.json()

        # Check for AV rate limit note
        if "Note" in quote_data and "Thank you for using Alpha Vantage" in quote_data["Note"]:
            raise ValueError("Alpha Vantage rate limit exceeded")

        overview_resp = await client.get(
            AV_BASE_URL,
            params={"function": "OVERVIEW", "symbol": symbol, "apikey": api_key},
        )
        overview = overview_resp.json()

        if "Note" in overview and "Thank you for using Alpha Vantage" in overview["Note"]:
            raise ValueError("Alpha Vantage rate limit exceeded")

    quote = quote_data.get("Global Quote", {})
    last_close_raw = quote.get("05. price")
    last_close = _safe_float(last_close_raw)

    return MarketDataSnapshot(
        symbol=symbol,
        company_name=overview.get("Name", symbol),
        pe_ratio=_safe_float(overview.get("PERatio")),
        market_cap=_safe_float(overview.get("MarketCapitalization")),
        fifty_two_week_high=_safe_float(overview.get("52WeekHigh")),
        fifty_two_week_low=_safe_float(overview.get("52WeekLow")),
        eps_trailing=_safe_float(overview.get("EPS")),
        revenue_ttm=_safe_float(overview.get("RevenueTTM")),
        gross_margin_pct=None,  # AV OVERVIEW does not provide gross margin %
        debt_to_equity=None,  # AV OVERVIEW does not include D/E ratio
        # AV GLOBAL_QUOTE is single-day only — no historical OHLCV
        price_history=[],
        last_close=last_close,
        is_degraded=False,
    )


# ---------------------------------------------------------------------------
# Disk cache: read / write with TTL (D-09, D-10, D-11)
# ---------------------------------------------------------------------------


async def _read_cache(
    symbol: str, cache_dir: Path | None = None
) -> MarketDataSnapshot | None:
    """Read a cached MarketDataSnapshot for symbol.

    Returns None if the cache file does not exist or is older than CACHE_TTL_SECONDS.
    """
    path = (cache_dir or CACHE_DIR) / f"{symbol}.json"
    if not path.exists():
        return None

    async with aiofiles.open(path) as fh:
        raw = await fh.read()
    data = json.loads(raw)

    # TTL check — always store/compare in UTC (Pitfall 5)
    cached_at_str: str = data["cached_at"]
    cached_at = datetime.fromisoformat(cached_at_str)
    # Ensure tz-aware for comparison
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - cached_at).total_seconds()
    if age > CACHE_TTL_SECONDS:
        return None  # Expired

    return MarketDataSnapshot.model_validate(data["snapshot"])


async def _write_cache(
    symbol: str, snapshot: MarketDataSnapshot, cache_dir: Path | None = None
) -> None:
    """Write a MarketDataSnapshot to disk cache using atomic temp-file-rename (D-11)."""
    dir_path = cache_dir or CACHE_DIR
    dir_path.mkdir(parents=True, exist_ok=True)

    payload = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    tmp_path = dir_path / f"{symbol}.json.tmp"
    final_path = dir_path / f"{symbol}.json"

    async with aiofiles.open(tmp_path, "w") as fh:
        await fh.write(json.dumps(payload, indent=2))

    tmp_path.rename(final_path)


# ---------------------------------------------------------------------------
# Per-ticker fetch with yfinance -> AV -> degraded fallback chain (D-15)
# ---------------------------------------------------------------------------


async def _fetch_single_ticker(
    symbol: str,
    company_name: str,
    av_key: str | None,
    cache_dir: Path | None = None,
) -> MarketDataSnapshot:
    """Fetch a single ticker with cache-first and yfinance -> AV -> degraded fallback.

    Per-ticker asyncio.Lock prevents concurrent yfinance access to the same symbol
    (D-06, Pitfall 1).
    """
    # Get or create per-ticker lock
    if symbol not in _ticker_locks:
        _ticker_locks[symbol] = asyncio.Lock()

    async with _ticker_locks[symbol]:
        # Cache-first (D-09)
        cached = await _read_cache(symbol, cache_dir)
        if cached is not None:
            logger.info("cache_hit", ticker=symbol)
            return cached

        snapshot: MarketDataSnapshot | None = None

        # 1. Try yfinance (D-01, D-02)
        try:
            data = await asyncio.to_thread(_fetch_yfinance_sync, symbol)
            snapshot = MarketDataSnapshot(
                symbol=symbol,
                company_name=data.get("company_name", company_name),
                price_history=data.get("price_history", []),
                pe_ratio=data.get("pe_ratio"),
                market_cap=data.get("market_cap"),
                fifty_two_week_high=data.get("fifty_two_week_high"),
                fifty_two_week_low=data.get("fifty_two_week_low"),
                eps_trailing=data.get("eps_trailing"),
                revenue_ttm=data.get("revenue_ttm"),
                gross_margin_pct=data.get("gross_margin_pct"),
                debt_to_equity=data.get("debt_to_equity"),
                earnings_surprise_pct=data.get("earnings_surprise_pct"),
                next_earnings_date=data.get("next_earnings_date"),
                last_close=data.get("last_close"),
                price_change_30d_pct=data.get("price_change_30d_pct"),
                price_change_90d_pct=data.get("price_change_90d_pct"),
                avg_volume_30d=data.get("avg_volume_30d"),
                is_degraded=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance_failed", ticker=symbol, error=str(exc))

        # 2. If yfinance failed and AV key present, try Alpha Vantage (D-08)
        if snapshot is None and av_key is not None:
            try:
                snapshot = await _fetch_alpha_vantage(symbol, av_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("alpha_vantage_failed", ticker=symbol, error=str(exc))

        # 3. Both failed — return degraded snapshot (D-15)
        if snapshot is None:
            logger.warning(
                "market_data_fetch_failed", ticker=symbol, reason="all sources failed"
            )
            return MarketDataSnapshot(
                symbol=symbol,
                company_name=company_name,
                is_degraded=True,
            )

        # Persist to cache before returning
        await _write_cache(symbol, snapshot, cache_dir)
        return snapshot


# ---------------------------------------------------------------------------
# Public entry point: parallel multi-ticker fetch (D-06, D-07)
# ---------------------------------------------------------------------------


async def fetch_market_data(
    tickers: list[ExtractedTicker],
    av_key: str | None = None,
    cache_dir: Path | None = None,
) -> dict[str, MarketDataSnapshot]:
    """Fetch market data for all tickers in parallel via asyncio.TaskGroup (D-06).

    Each ticker is fetched concurrently. Per-ticker locks inside
    _fetch_single_ticker prevent yfinance thread-safety issues for
    duplicate symbols. Returns a dict keyed by ticker symbol.
    """
    results: dict[str, MarketDataSnapshot] = {}

    async def _fetch_and_store(ticker: ExtractedTicker) -> None:
        snapshot = await _fetch_single_ticker(
            ticker.symbol, ticker.company_name, av_key, cache_dir
        )
        results[ticker.symbol] = snapshot

    async with asyncio.TaskGroup() as tg:
        for ticker in tickers:
            tg.create_task(_fetch_and_store(ticker))

    return results
