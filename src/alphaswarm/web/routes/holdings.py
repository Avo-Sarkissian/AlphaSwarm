"""HOLD-03: GET /api/holdings — REST surface for the eager-loaded PortfolioSnapshot.

This is the ONE and ONLY web route module permitted by the importlinter contract
(`pyproject.toml` [tool.importlinter]) to import `alphaswarm.holdings`. The
whitelist entry lives in `tests/invariants/test_importlinter_coverage.py`
(`_KNOWN_NON_SOURCE`). Adding this module to `pyproject.toml` `source_modules`
would break `test_source_modules_does_not_list_whitelisted_packages`.

The `load_portfolio_snapshot` helper (synchronous, at module scope) lives here
specifically so that `alphaswarm.web.app` — which IS in `source_modules` and
therefore cannot import `alphaswarm.holdings.*` — can call it via
`await asyncio.to_thread(load_portfolio_snapshot, ...)` at lifespan startup.
This is the D-04 whitelist indirection architecture; see Task 3 of Plan 39-02
for the lifespan wiring and the Codex HIGH review closure notes.

Decisions implemented:
- D-06: response shape = account_number_hash + as_of (ISO-8601) + holdings list;
        Decimal fields serialized as strings to avoid float precision loss.
- D-07: handler reads request.app.state.portfolio_snapshot ONLY — no CSV I/O at
        request time. `load_portfolio_snapshot` is called ONCE at lifespan.
- D-08: portfolio_snapshot is None (lifespan loader failed) → 503 with a
        FastAPI-wrapped generic body `{"detail": {"error": "holdings_unavailable",
        "message": "..."}}`. The raw exception and filesystem path are logged
        server-side by `load_portfolio_snapshot` — the client sees only
        "holdings_unavailable" inside the `detail` dict (T-39-06 from Plan 01
        threat model).

Review closures (39-REVIEWS.md):
- Codex HIGH (import boundary): `web/app.py` imports `load_portfolio_snapshot`
  from THIS module, not from `alphaswarm.holdings.*`. `uv run lint-imports` is
  an explicit verify-before-code gate in Task 3.
- Codex MEDIUM (503 body FastAPI wrapping): `HTTPException(detail={...})`
  serializes as `{"detail": {...}}`. Task 4 integration tests assert
  `r.json()["detail"]["error"]` to match this shape. No `JSONResponse` switch.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.holdings import PortfolioSnapshot
from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError

log = structlog.get_logger(component="web.holdings")

router = APIRouter()


class HoldingOut(BaseModel):
    """D-06: a single Holding serialized for the JSON response.

    Decimal fields are serialized as strings (`str(decimal_value)`) to preserve
    precision across JSON — float would silently drop significant digits for
    fractional shares like 101.3071. See Pitfall 1 in 39-RESEARCH.md.
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
    """Return the cached PortfolioSnapshot loaded at lifespan startup (D-07).

    Raises:
        HTTPException(503, detail={"error": "holdings_unavailable", ...}): when
            `request.app.state.portfolio_snapshot is None`, which means the
            lifespan `load_portfolio_snapshot` helper caught `HoldingsLoadError`
            and returned None (D-08). FastAPI wraps `detail` under a top-level
            `detail` key — the actual wire shape is
            `{"detail": {"error": "holdings_unavailable", "message": "..."}}`.
            The 503 body is intentionally generic — the raw filesystem path
            and HoldingsLoadError message are logged server-side but NEVER
            returned in the response (T-39-06; review closure Codex MEDIUM).
    """
    snapshot: PortfolioSnapshot | None = getattr(
        request.app.state, "portfolio_snapshot", None,
    )
    if snapshot is None:
        # Generic body — no path, no exception text. See T-39-06.
        log.warning("holdings_unavailable_requested")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "holdings_unavailable",
                "message": "Holdings file could not be loaded at startup",
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
    """Lifespan-only synchronous helper: load the Schwab CSV into a PortfolioSnapshot.

    Lives in the route module (on the D-04 `_KNOWN_NON_SOURCE` whitelist) so
    `alphaswarm.web.app` — which is in importlinter `source_modules` — can
    import and call this function without importing `alphaswarm.holdings.*`
    directly. This is the indirection layer that keeps the importlinter
    forbidden contract satisfied while still allowing eager startup loading.

    The function is SYNCHRONOUS: it uses `csv.DictReader`, `Decimal(str)`, and
    `Path.open()` — all blocking I/O. The FastAPI lifespan in `web/app.py` MUST
    offload this call via `await asyncio.to_thread(load_portfolio_snapshot, path)`
    to satisfy CLAUDE.md Hard Constraint 1 ("no blocking I/O on the main event
    loop"). See Task 3 of Plan 39-02 for the to_thread wiring (review closure
    for Codex MEDIUM).

    Returns:
        PortfolioSnapshot on success — caller stores on app.state.portfolio_snapshot.
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
