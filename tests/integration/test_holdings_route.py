"""HOLD-03 integration tests for GET /api/holdings.

Lives under tests/integration/ so that tests/integration/conftest.py auto-applies
the enable_socket marker — FastAPI TestClient needs in-process sockets even
though no outbound network traffic occurs.

Tests are hermetic: they build a minimal FastAPI app with a custom lifespan that
directly seeds app.state.portfolio_snapshot. HoldingsLoader is NEVER invoked and
Schwab/holdings.csv is NEVER read. This isolates the test surface to the route
module + pydantic serialization.

Covers:
- 200 happy path + response structure (D-06)
- 503 when snapshot is None (D-08), with generic body (T-39-06: no filesystem
  path in the response). 503 body is FastAPI-wrapped as {"detail": {...}}
  (review closure: Codex MEDIUM — HTTPException(detail=...) always nests under
  a top-level "detail" key; see test_get_holdings_503_body_is_detail_wrapped).
- Decimal-as-string serialization for qty and cost_basis (Pitfall 1)
- cost_basis passes through as null when the source Holding.cost_basis is None
- as_of rendered as ISO-8601 with +00:00 suffix
- Row order preserved across serialization
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.holdings import Holding, PortfolioSnapshot
from alphaswarm.web.routes.holdings import router as holdings_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_holdings_test_app(snapshot: PortfolioSnapshot | None) -> FastAPI:
    """Build a minimal FastAPI app for GET /api/holdings tests.

    The lifespan seeds app.state.portfolio_snapshot directly with the argument;
    HoldingsLoader is not invoked and no filesystem I/O happens. Mirrors the
    _make_report_test_app pattern in tests/test_web_report.py (omits the
    report-specific state).
    """

    @asynccontextmanager
    async def _holdings_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.portfolio_snapshot = snapshot
        yield

    app = FastAPI(title="AlphaSwarm-Holdings-Test", lifespan=_holdings_lifespan)
    app.include_router(holdings_router, prefix="/api")
    return app


def _sample_snapshot(
    *,
    holdings: tuple[Holding, ...] | None = None,
    as_of: datetime | None = None,
    account_number_hash: str = "abcd1234",
) -> PortfolioSnapshot:
    """Build a canonical PortfolioSnapshot for the happy-path tests."""
    return PortfolioSnapshot(
        holdings=holdings
        or (
            Holding(
                ticker="AAPL",
                qty=Decimal("101.3071"),
                cost_basis=Decimal("101.3071") * Decimal("165.5365"),
            ),
            Holding(ticker="SWYXX", qty=Decimal("10000"), cost_basis=None),
        ),
        as_of=as_of or datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC),
        account_number_hash=account_number_hash,
    )


# ---------------------------------------------------------------------------
# 200 happy path (D-06 response shape)
# ---------------------------------------------------------------------------


def test_get_holdings_200() -> None:
    """HOLD-03 — 200 returns serialized PortfolioSnapshot with D-06 shape."""
    snapshot = _sample_snapshot()
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"account_number_hash", "as_of", "holdings"}
        assert body["account_number_hash"] == "abcd1234"
        assert isinstance(body["as_of"], str)
        assert isinstance(body["holdings"], list)
        assert len(body["holdings"]) == 2
        for item in body["holdings"]:
            assert set(item.keys()) == {"ticker", "qty", "cost_basis"}
            assert isinstance(item["ticker"], str)
            assert isinstance(item["qty"], str)  # Decimal → str, Pitfall 1
            assert item["cost_basis"] is None or isinstance(item["cost_basis"], str)


def test_get_holdings_preserves_row_order() -> None:
    """Holdings tuple order is preserved across pydantic serialization."""
    snapshot = _sample_snapshot(
        holdings=(
            Holding(ticker="QQQ", qty=Decimal("6"), cost_basis=Decimal("422")),
            Holding(ticker="CRDO", qty=Decimal("31"), cost_basis=Decimal("111")),
            Holding(ticker="MRVL", qty=Decimal("48"), cost_basis=Decimal("79")),
        ),
    )
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        tickers = [h["ticker"] for h in r.json()["holdings"]]
        assert tickers == ["QQQ", "CRDO", "MRVL"]


def test_get_holdings_account_hash_round_trip() -> None:
    """account_number_hash passes through unchanged."""
    snapshot = _sample_snapshot(account_number_hash="deadbeef")
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        assert r.json()["account_number_hash"] == "deadbeef"


# ---------------------------------------------------------------------------
# Decimal-as-string serialization (D-06, Pitfall 1)
# ---------------------------------------------------------------------------


def test_get_holdings_qty_is_string_not_float() -> None:
    """Pitfall 1 — qty is Decimal-as-string. Exact fractional shares preserved."""
    snapshot = _sample_snapshot(
        holdings=(
            Holding(
                ticker="AAPL",
                qty=Decimal("101.3071"),
                cost_basis=Decimal("1000.00"),
            ),
        ),
    )
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        assert r.json()["holdings"][0]["qty"] == "101.3071"
        # Not a float (JSON numbers serialize without trailing zeros; strings keep them)
        assert not isinstance(r.json()["holdings"][0]["qty"], float)


def test_get_holdings_cost_basis_is_string_not_float() -> None:
    """Pitfall 1 — cost_basis is str(Decimal), preserves computed product exactly."""
    expected_cost = Decimal("101.3071") * Decimal("165.5365")
    snapshot = _sample_snapshot(
        holdings=(
            Holding(
                ticker="AAPL",
                qty=Decimal("101.3071"),
                cost_basis=expected_cost,
            ),
        ),
    )
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        cost_str = r.json()["holdings"][0]["cost_basis"]
        assert isinstance(cost_str, str)
        assert cost_str == str(expected_cost)
        # Round-trips back to the exact same Decimal
        assert Decimal(cost_str) == expected_cost


def test_get_holdings_cost_basis_null_when_none() -> None:
    """Holding.cost_basis=None → JSON null (not the string 'None')."""
    snapshot = _sample_snapshot(
        holdings=(
            Holding(ticker="SWYXX", qty=Decimal("10000"), cost_basis=None),
        ),
    )
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        assert r.json()["holdings"][0]["cost_basis"] is None


def test_get_holdings_as_of_is_iso8601_with_tz() -> None:
    """as_of is ISO-8601 with +00:00 tz suffix (tz-aware UTC)."""
    snapshot = _sample_snapshot(
        as_of=datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC),
    )
    app = _make_holdings_test_app(snapshot)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 200
        as_of = r.json()["as_of"]
        assert as_of == "2026-04-18T12:34:56+00:00"
        # Round-trips via datetime.fromisoformat
        parsed = datetime.fromisoformat(as_of)
        assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# 503 fallback path (D-08, T-39-06; FastAPI detail-wrapping per Codex MEDIUM)
# ---------------------------------------------------------------------------


def test_get_holdings_503_when_snapshot_none() -> None:
    """D-08 — 503 with locked body when app.state.portfolio_snapshot is None.

    FastAPI's HTTPException(detail={...}) wraps the detail dict under a
    top-level "detail" key. Assertions read r.json()["detail"][...] to match
    the actual wire shape (review closure: Codex MEDIUM).
    """
    app = _make_holdings_test_app(None)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert detail["error"] == "holdings_unavailable"
        assert detail["message"] == "Holdings file could not be loaded at startup"


def test_get_holdings_503_body_is_detail_wrapped() -> None:
    """Review closure: Codex MEDIUM — regression that pins the 503 body shape
    as FastAPI's HTTPException wrapping (top-level `detail` key).

    If a future change switches to `JSONResponse(status_code=503, content={...})`
    for a top-level `{"error": ..., "message": ...}` body, this test will flag
    the divergence and the 39-02 plan's must_haves must be updated in tandem.
    """
    app = _make_holdings_test_app(None)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 503
        body = r.json()
        # Top-level shape: {"detail": {...}} — not {"error": ..., "message": ...}
        assert set(body.keys()) == {"detail"}, (
            f"Expected only 'detail' at top level, got: {list(body.keys())}"
        )
        assert "error" not in body, "error lives inside detail, not at top level"
        assert "message" not in body, "message lives inside detail, not at top level"
        assert isinstance(body["detail"], dict)
        assert set(body["detail"].keys()) == {"error", "message"}


def test_get_holdings_503_body_does_not_leak_path() -> None:
    """T-39-06 — 503 response body must not contain the filesystem path or
    any HoldingsLoadError message fragment. The loader exception is logged
    server-side only; the client sees only the generic error code."""
    app = _make_holdings_test_app(None)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
        assert r.status_code == 503
        body_text = r.text
        # No filesystem path markers
        assert "Schwab" not in body_text
        assert ".csv" not in body_text
        assert "holdings_csv_path" not in body_text
        # No absolute-path markers
        assert "/Schwab/" not in body_text
        assert "/tmp/" not in body_text


# ---------------------------------------------------------------------------
# Source-file invariants (Pitfall 1 + Pitfall 7 grep guards)
# ---------------------------------------------------------------------------


def test_route_source_uses_str_not_float_for_serialization() -> None:
    """Pitfall 1 — route source MUST NOT call float() on Holding fields."""
    from pathlib import Path as _Path
    src = _Path(__file__).parent.parent.parent / "src/alphaswarm/web/routes/holdings.py"
    content = src.read_text(encoding="utf-8")
    assert "str(h.qty)" in content, "Route must use str(h.qty) for Decimal serialization"
    assert "float(h.qty)" not in content
    assert "float(h.cost_basis)" not in content


def test_route_source_does_not_log_holding_field_values() -> None:
    """Pitfall 7 / ISOL-07 — route handler must not log ticker/qty/cost_basis."""
    import re
    from pathlib import Path as _Path
    src = _Path(__file__).parent.parent.parent / "src/alphaswarm/web/routes/holdings.py"
    content = src.read_text(encoding="utf-8")
    for forbidden in (
        r"log\.info\([^)]*qty=",
        r"log\.info\([^)]*ticker=",
        r"log\.info\([^)]*cost_basis=",
    ):
        assert not re.search(forbidden, content), (
            f"holdings.py must not log Holding field values — matched {forbidden!r}"
        )


def test_web_app_uses_asyncio_to_thread_for_holdings_load() -> None:
    """Review closure: Codex MEDIUM — lifespan MUST wrap load_portfolio_snapshot
    in asyncio.to_thread so the synchronous CSV parsing never blocks uvicorn's
    event loop (CLAUDE.md Hard Constraint 1)."""
    from pathlib import Path as _Path
    src = _Path(__file__).parent.parent.parent / "src/alphaswarm/web/app.py"
    content = src.read_text(encoding="utf-8")
    assert "asyncio.to_thread(load_portfolio_snapshot," in content, (
        "web/app.py must use asyncio.to_thread(load_portfolio_snapshot, ...) "
        "in the lifespan — synchronous calls would block the event loop."
    )


def test_web_app_does_not_import_alphaswarm_holdings_directly() -> None:
    """Review closure: Codex HIGH — web/app.py is in importlinter source_modules
    and CANNOT import alphaswarm.holdings.* directly. The D-04 helper
    indirection via alphaswarm.web.routes.holdings is the only legal path."""
    import re
    from pathlib import Path as _Path
    src = _Path(__file__).parent.parent.parent / "src/alphaswarm/web/app.py"
    content = src.read_text(encoding="utf-8")
    # Forbidden: "from alphaswarm.holdings " or "from alphaswarm.holdings."
    forbidden = re.compile(r"^from alphaswarm\.holdings(\s|\.)", re.MULTILINE)
    matches = forbidden.findall(content)
    assert not matches, (
        f"web/app.py MUST NOT import alphaswarm.holdings.* directly — "
        f"use load_portfolio_snapshot from alphaswarm.web.routes.holdings "
        f"(D-04 whitelist). Forbidden matches: {matches}"
    )
