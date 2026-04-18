"""INGEST-01 integration tests — real network.

These tests are auto-marked (enable_socket) by
tests/integration/conftest.py — without that marker the global
`--disable-socket` gate would block real network access.

PATH DEPENDENCY (Codex review): the enable_socket marker is applied by a
conftest.py hook that matches on the string "tests/integration" in the item
fspath. Moving this test file outside tests/integration/ would silently
remove the marker and the global --disable-socket gate would block every
real-network call with SocketBlockedError. The test
`test_test_module_lives_under_tests_integration` at the bottom of this
module asserts the file remains under tests/integration/ so the invariant
is loud, not silent.

Content shape: we assert `staleness='fresh'` and loose type/positivity
checks (price > 0, isinstance Decimal). We do NOT assert specific price
values because they change live.

Flake tolerance (Codex review): these tests are best-effort real-network.
If Yahoo is rate-limiting or the CI IP range is blocked, the provider
returns fetch_failed and the 'fresh' assertions will fail. That's a real
signal of upstream degradation, not a false positive. The delisted-ticker
test accepts either fetch_failed OR a structurally valid empty slice so
yfinance error-semantic drift does not flake the suite. For local dev,
run `uv run pytest tests/integration/` to exercise.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

from alphaswarm.ingestion import MarketSlice, YFinanceMarketDataProvider


async def test_yfinance_real_fetch_aapl_returns_fresh_slice() -> None:
    """Validates INGEST-01 end-to-end against live Yahoo backend."""
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL"])
    assert "AAPL" in result
    slice_ = result["AAPL"]
    assert isinstance(slice_, MarketSlice)
    assert slice_.staleness == "fresh", (
        f"AAPL should fetch fresh; got {slice_.staleness}. "
        "If this fails repeatedly, Yahoo is rate-limiting or the yfinance "
        "FastInfo shape changed — re-run RESEARCH probe."
    )
    assert slice_.source == "yfinance"
    assert slice_.price is not None
    assert isinstance(slice_.price, Decimal)
    assert slice_.price > Decimal("0")


async def test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed() -> None:
    """Pitfall 1 / D-19 regression guard in the real environment.

    TICKER LITERAL (Codex review): 'ZZZZNOTREAL' was chosen because it is a
    stably-unknown symbol at the 2026-04-18 probe — yfinance raises
    KeyError('currentTradingPeriod') on fast_info.last_price for it. If a
    future yfinance release changes this error semantic (e.g., returns an
    empty slice instead of raising), the TOLERANT assertion below still
    holds (D-19 still requires the slice to either be fetch_failed OR a
    structurally valid slice with price is None — the provider must never
    raise). If the literal 'ZZZZNOTREAL' ever becomes a real listed
    symbol, swap it for any other 10-char Z-prefixed nonsense string.
    """
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["ZZZZNOTREAL"])  # MUST NOT raise — D-19
    assert "ZZZZNOTREAL" in result
    slice_ = result["ZZZZNOTREAL"]
    assert isinstance(slice_, MarketSlice)
    assert slice_.source == "yfinance"
    # Tolerant outcome (Codex review): D-19 says "never raise"; yfinance
    # may signal an unknown ticker via (a) raising, caught by broad
    # try/except -> staleness='fetch_failed', or (b) returning an empty
    # info dict -> staleness='fresh' with price is None. Both outcomes
    # prove the contract; we accept either and fail only if BOTH the
    # slice claims fresh AND price is populated (i.e., Yahoo started
    # serving data for a nonsense ticker, which would itself be a
    # regression worth investigating).
    if slice_.staleness == "fetch_failed":
        assert slice_.price is None
    else:
        assert slice_.staleness == "fresh"
        assert slice_.price is None, (
            f"Expected ZZZZNOTREAL to yield either fetch_failed OR a "
            f"structurally empty slice; got staleness=fresh with "
            f"price={slice_.price!r}. If the literal is now a real ticker, "
            "swap it for another Z-prefixed nonsense symbol."
        )


async def test_yfinance_real_batch_with_good_and_bad_ticker_returns_both_slices() -> None:
    """D-05 per-ticker error isolation against the real backend — one bad
    ticker must not fail the batch; both slices are returned.

    Tolerance (Codex review): the bad-ticker slice is either fetch_failed
    or a structurally valid empty slice — either proves isolation held."""
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL", "ZZZZNOTREAL"])
    assert set(result.keys()) == {"AAPL", "ZZZZNOTREAL"}
    assert result["AAPL"].staleness == "fresh"
    bad = result["ZZZZNOTREAL"]
    assert bad.staleness in {"fetch_failed", "fresh"}
    if bad.staleness == "fresh":
        assert bad.price is None  # tolerant: yfinance may return empty slice


async def test_yfinance_real_fetch_fundamentals_returns_at_least_one_field() -> None:
    """D-06 — .info mapping path works against real Yahoo for a liquid ticker.
    AAPL reliably has trailingPE and marketCap; at least one fundamentals
    Decimal field must be populated."""
    provider = YFinanceMarketDataProvider()
    result = await provider.get_fundamentals(["AAPL"])
    assert result["AAPL"].staleness == "fresh"
    fundamentals = result["AAPL"].fundamentals
    assert fundamentals is not None
    populated = [fundamentals.pe_ratio, fundamentals.eps, fundamentals.market_cap]
    assert any(f is not None for f in populated), (
        "Expected at least one of (pe_ratio, eps, market_cap) to be populated "
        f"for AAPL; got {fundamentals}"
    )
    for field in populated:
        if field is not None:
            assert isinstance(field, Decimal)


async def test_yfinance_real_empty_list_returns_empty_dict() -> None:
    """Pitfall 9 — empty list short-circuits before network. Integration
    confirms the guard also holds when enable_socket is active."""
    provider = YFinanceMarketDataProvider()
    assert await provider.get_prices([]) == {}


def test_test_module_lives_under_tests_integration() -> None:
    """Codex review — invariant: this module MUST live under tests/integration/
    so the conftest enable_socket auto-marker applies. If relocated, the
    other tests in this file would silently fail under --disable-socket."""
    here = pathlib.Path(__file__).resolve()
    assert "tests/integration" in str(here), (
        f"{here} is outside tests/integration/ — the enable_socket auto-marker "
        "from conftest.py will not apply and the global --disable-socket gate "
        "will block real-network fetches. Move this file back under "
        "tests/integration/."
    )
