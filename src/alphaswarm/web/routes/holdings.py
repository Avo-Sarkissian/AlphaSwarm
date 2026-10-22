"""HOLD-03: GET /api/holdings — REST surface for the eager-loaded PortfolioSnapshot.

This is the ONE and ONLY web route module permitted by the importlinter contract
(`pyproject.toml` [tool.importlinter]) to import `alphaswarm.holdings`. The
whitelist entry lives in `tests/invariants/test_importlinter_coverage.py`
(`_KNOWN_NON_SOURCE`). Adding this module to `pyproject.toml` `source_modules`
would break `test_source_modules_does_not_list_whitelisted_packages`.

`PortfolioCache` and its synchronous `load_portfolio_snapshot` helper live here
specifically so that `alphaswarm.web.app` — which IS in `source_modules` and
therefore cannot import `alphaswarm.holdings.*` — can build the cache at
lifespan startup; the cache runs the helper via `asyncio.to_thread`. This is
the D-04 whitelist indirection architecture.

Decisions implemented:
- D-06: response shape = account_number_hash + as_of (ISO-8601) + holdings list;
        Decimal fields serialized as strings to avoid float precision loss.
- D-07 (revised): the handler reads app.state.portfolio_cache, which reloads the
        CSV when its mtime changes; no parse happens unless the file changed.
- D-08: PortfolioCache.get() returns None (file missing or malformed) → 503 with a
        FastAPI-wrapped generic body `{"detail": {"error": "holdings_unavailable",
        "message": "..."}}`. The raw exception and filesystem path are logged
        server-side by `load_portfolio_snapshot` — the client sees only
        "holdings_unavailable" inside the `detail` dict (T-39-06 from Plan 01
        threat model).

Review closures:
- Codex HIGH (import boundary): `web/app.py` imports `PortfolioCache`
  from THIS module, not from `alphaswarm.holdings.*`. `uv run lint-imports` is
  an explicit verify-before-code gate in Task 3.
- Codex MEDIUM (503 body FastAPI wrapping): `HTTPException(detail={...})`
  serializes as `{"detail": {...}}`. Task 4 integration tests assert
  `r.json()["detail"]["error"]` to match this shape. No `JSONResponse` switch.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.holdings import PortfolioSnapshot
from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError

log = structlog.get_logger(component="web.holdings")

router = APIRouter()


class PortfolioCache:
    """Holdings snapshot that reloads when the CSV's mtime changes.

    Lives at ``app.state.portfolio_cache`` and is never assigned onto AppState
    (docs/DECISIONS.md#adr-holdings-isolation). The stat and the parse run in a
    worker thread; a malformed file yields None until the file changes again.
    """

    def __init__(self, csv_path: Path) -> None:
        self._csv_path = csv_path
        self._lock = asyncio.Lock()
        self._mtime_ns: int | None = None
        self._snapshot: PortfolioSnapshot | None = None

    @property
    def holdings_as_of(self) -> datetime | None:
        """``as_of`` of the current snapshot, or None when none is loaded."""
        return self._snapshot.as_of if self._snapshot is not None else None

    async def get(self) -> PortfolioSnapshot | None:
        """Current snapshot, re-reading the CSV first when its mtime changed."""
        async with self._lock:
            mtime_ns = await asyncio.to_thread(_mtime_ns, self._csv_path)
            if mtime_ns is None:
                if self._mtime_ns is not None:
                    log.warning("holdings_file_disappeared")
                self._snapshot = None
                self._mtime_ns = None
                return None
            if mtime_ns != self._mtime_ns:
                self._snapshot = await asyncio.to_thread(load_portfolio_snapshot, self._csv_path)
                self._mtime_ns = mtime_ns
                log.info("holdings_snapshot_reloaded", loaded=self._snapshot is not None)
            return self._snapshot


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class HoldingOut(BaseModel):
    """D-06: a single Holding serialized for the JSON response.

    Decimal fields are serialized as strings (`str(decimal_value)`) to preserve
    precision across JSON — float would silently drop significant digits for
    fractional shares like 12.3456 (docs/DECISIONS.md#p39-d-06).
    """

    ticker: str
    qty: str
    cost_basis: str | None


class HoldingsResponse(BaseModel):
    """D-06: serialized PortfolioSnapshot for GET /api/holdings."""

    account_number_hash: str
    as_of: str  # ISO-8601 — datetime.isoformat() on tz-aware UTC produces `...+00:00`
    holdings: list[HoldingOut]


@router.get("/holdings", response_model=HoldingsResponse)
async def get_holdings(request: Request) -> HoldingsResponse:
    """Return the PortfolioSnapshot from app.state.portfolio_cache (D-07).

    Raises:
        HTTPException(503, detail={"error": "holdings_unavailable", ...}): when
            `PortfolioCache.get()` returns None: the file is missing, or
            `load_portfolio_snapshot` caught `HoldingsLoadError` (D-08).
            FastAPI wraps `detail` under a top-level
            `detail` key — the actual wire shape is
            `{"detail": {"error": "holdings_unavailable", "message": "..."}}`.
            The 503 body is intentionally generic — the raw filesystem path
            and HoldingsLoadError message are logged server-side but NEVER
            returned in the response (T-39-06; review closure Codex MEDIUM).
    """
    cache: PortfolioCache = request.app.state.portfolio_cache
    snapshot = await cache.get()
    if snapshot is None:
        # Generic body — no path, no exception text. See T-39-06.
        log.warning("holdings_unavailable_requested")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "holdings_unavailable",
                "message": "Holdings file could not be loaded",
            },
        )

    return HoldingsResponse(
        account_number_hash=snapshot.account_number_hash,
        as_of=snapshot.as_of.isoformat(),
        holdings=[
            HoldingOut(
                ticker=h.ticker,
                qty=str(h.qty),  # Decimal → str (Pitfall 1; NEVER float())
                cost_basis=(str(h.cost_basis) if h.cost_basis is not None else None),
            )
            for h in snapshot.holdings
        ],
    )


def load_portfolio_snapshot(csv_path: Path) -> PortfolioSnapshot | None:
    """Synchronous helper behind PortfolioCache: load the CSV into a PortfolioSnapshot.

    Lives in the route module (on the D-04 `_KNOWN_NON_SOURCE` whitelist) so
    `alphaswarm.web.app` — which is in importlinter `source_modules` — never
    imports `alphaswarm.holdings.*` directly. This is the indirection layer that
    keeps the importlinter forbidden contract satisfied while still allowing
    eager startup loading.

    The function is SYNCHRONOUS: it uses `csv.DictReader`, `Decimal(str)`, and
    `Path.open()` — all blocking I/O. `PortfolioCache.get()` MUST offload this
    call via `await asyncio.to_thread(load_portfolio_snapshot, path)` to satisfy
    CLAUDE.md Hard Constraint 1 ("no blocking I/O on the main event loop").

    Returns:
        PortfolioSnapshot on success — PortfolioCache keeps it.
        None on `HoldingsLoadError` — caller stores None; GET /api/holdings
        returns 503 (D-08). The exception is NEVER re-raised from this helper.

    Args:
        csv_path: Filesystem path to the Schwab holdings CSV. Typically
            `settings.holdings_csv_path` (D-05). Logged on success/failure but
            never echoed into the HTTP 503 response (T-39-06).
    """
    try:
        snapshot = HoldingsLoader.load(csv_path)
    except HoldingsLoadError as exc:
        # D-08: narrow except — only HoldingsLoadError is converted to None.
        # Any other exception propagates (fail-loud, not silent).
        log.error(
            "holdings_load_failed",
            error=str(exc),
            path=str(csv_path),
        )
        return None

    log.info(
        "holdings_snapshot_ready",
        path=str(csv_path),
        count=len(snapshot.holdings),
    )
    return snapshot
