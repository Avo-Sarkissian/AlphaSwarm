"""INGEST-01 unit tests — monkeypatched yf.Ticker, no real network.

pytest-asyncio asyncio_mode='auto' is configured project-wide — async tests do
not need @pytest.mark.asyncio.

pytest-socket --disable-socket is active globally (pyproject.toml). These tests
MUST NOT hit real network — every yf.Ticker access is monkeypatched. If a test
regresses and hits real network, pytest-socket raises SocketBlockedError.
"""

from __future__ import annotations

import inspect
import pathlib
from decimal import Decimal
from typing import Any

import pytest

from alphaswarm.ingestion import MarketDataProvider, MarketSlice, YFinanceMarketDataProvider
from alphaswarm.ingestion.yfinance_provider import _decimal_or_none

# --------- Monkeypatch helpers ---------


class _FakeFastInfo:
    last_price: float = 270.23
    last_volume: int = 61_314_800
    market_cap: float = 3.971820552192e12


class _FakeTicker:
    """Happy-path fake — returns AAPL-shaped data for any ticker symbol."""

    def __init__(self, ticker: str) -> None:
        self._ticker = ticker

    @property
    def fast_info(self) -> _FakeFastInfo:
        return _FakeFastInfo()

    @property
    def info(self) -> dict[str, Any]:
        return {
            "trailingPE": 34.25,
            "trailingEps": 7.89,
            "marketCap": 3_971_820_552_192,
        }


class _BinaryFloatFastInfo:
    last_price: float = 0.1  # pathological binary float — Pitfall 5 probe
    last_volume: int = 100
    market_cap: float = 1.0e9


class _BinaryFloatTicker:
    def __init__(self, ticker: str) -> None:
        pass

    @property
    def fast_info(self) -> _BinaryFloatFastInfo:
        return _BinaryFloatFastInfo()

    @property
    def info(self) -> dict[str, Any]:
        return {"trailingPE": 0.1, "trailingEps": None, "marketCap": None}


class _NanFastInfo:
    last_price: float = 100.0
    last_volume: int = 1000
    market_cap: float = 1.0e9


class _NanTrailingPeTicker:
    """Pre-earnings company fake — trailingPE is float('nan') (Gemini review)."""

    def __init__(self, ticker: str) -> None:
        pass

    @property
    def fast_info(self) -> _NanFastInfo:
        return _NanFastInfo()

    @property
    def info(self) -> dict[str, Any]:
        return {
            "trailingPE": float("nan"),
            "trailingEps": 5.0,
            "marketCap": 1_000_000_000,
        }


class _InfFundamentalsTicker:
    """Inf/-Inf in fundamentals must be guarded to None."""

    def __init__(self, ticker: str) -> None:
        pass

    @property
    def fast_info(self) -> _NanFastInfo:
        return _NanFastInfo()

    @property
    def info(self) -> dict[str, Any]:
        return {
            "trailingPE": float("inf"),
            "trailingEps": float("-inf"),
            "marketCap": 1_000_000_000,
        }


class _KeyErrorFastInfo:
    """Simulates Pitfall 1: fast_info.last_price raises KeyError on delisted tickers."""

    @property
    def last_price(self) -> float:
        raise KeyError("currentTradingPeriod")

    last_volume: None = None
    market_cap: None = None


class _KeyErrorTicker:
    def __init__(self, ticker: str) -> None:
        pass

    @property
    def fast_info(self) -> _KeyErrorFastInfo:
        return _KeyErrorFastInfo()

    @property
    def info(self) -> dict[str, Any]:
        return {}


class _ExplodingTicker:
    """Constructor raises — hits the outermost try/except."""

    def __init__(self, ticker: str) -> None:
        raise RuntimeError("boom")


# --------- Async signature & Protocol conformance ---------


def test_all_methods_are_async_def() -> None:
    provider = YFinanceMarketDataProvider()
    for method_name in ("get_prices", "get_fundamentals", "get_volume"):
        method = getattr(provider, method_name)
        assert inspect.iscoroutinefunction(method), (
            f"YFinanceMarketDataProvider.{method_name} must be `async def`"
        )


async def _market_consumer(p: MarketDataProvider) -> list[str]:
    """mypy conformance probe — YFinanceMarketDataProvider must structurally conform."""
    result = await p.get_prices(["AAPL"])
    return list(result.keys())


async def test_structural_conformance_against_market_data_provider_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("alphaswarm.ingestion.yfinance_provider.yf.Ticker", _FakeTicker)
    provider = YFinanceMarketDataProvider()
    keys = await _market_consumer(provider)
    assert keys == ["AAPL"]


# --------- Field mapping ---------


async def test_get_prices_returns_market_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alphaswarm.ingestion.yfinance_provider.yf.Ticker", _FakeTicker)
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL"])
    assert "AAPL" in result
    s = result["AAPL"]
    assert isinstance(s, MarketSlice)
    assert s.price == Decimal("270.23")
    assert s.volume == 61_314_800
    assert s.fundamentals is not None
    assert s.fundamentals.pe_ratio == Decimal("34.25")
    assert s.fundamentals.eps == Decimal("7.89")
    assert s.fundamentals.market_cap == Decimal("3971820552192")
    assert s.staleness == "fresh"
    assert s.source == "yfinance"


async def test_decimal_precision_not_float(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pitfall 5 — Decimal(str(0.1)) == Decimal('0.1'), NOT the 60-digit binary
    expansion Decimal(0.1) produces."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _BinaryFloatTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["X"])
    assert result["X"].price == Decimal("0.1")
    assert result["X"].fundamentals is not None
    assert result["X"].fundamentals.pe_ratio == Decimal("0.1")


async def test_get_fundamentals_and_get_volume_return_same_slice_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 3 Protocol methods delegate to _fetch_batch_shared — same slice content."""
    monkeypatch.setattr("alphaswarm.ingestion.yfinance_provider.yf.Ticker", _FakeTicker)
    provider = YFinanceMarketDataProvider()
    prices = await provider.get_prices(["AAPL"])
    fundamentals = await provider.get_fundamentals(["AAPL"])
    volume = await provider.get_volume(["AAPL"])
    assert prices["AAPL"].price == fundamentals["AAPL"].price == volume["AAPL"].price
    assert prices["AAPL"].volume == fundamentals["AAPL"].volume == volume["AAPL"].volume
    assert prices["AAPL"].fundamentals == fundamentals["AAPL"].fundamentals


# --------- NaN/Inf guard (Gemini review) ---------


def test_decimal_or_none_unit() -> None:
    """Direct unit coverage on the _decimal_or_none helper (Gemini review fix).

    yfinance returns float('nan') for trailingPE on pre-earnings companies.
    Without the guard, Decimal(str(float('nan'))) produces Decimal('NaN') —
    a special Decimal value that is NOT None — which would break Phase 40
    advisory synthesis equality/comparison logic."""
    assert _decimal_or_none(None) is None
    assert _decimal_or_none(float("nan")) is None
    assert _decimal_or_none(float("inf")) is None
    assert _decimal_or_none(float("-inf")) is None
    assert _decimal_or_none(0.1) == Decimal("0.1")
    assert _decimal_or_none(42) == Decimal("42")
    assert _decimal_or_none(270.23) == Decimal("270.23")


async def test_nan_trailing_pe_is_guarded_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini review MEDIUM — yfinance returns float('nan') for trailingPE on
    pre-earnings companies. _decimal_or_none must return None, NOT Decimal('NaN').
    Other populated fundamentals must still round-trip to Decimal normally."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _NanTrailingPeTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["PRELAUNCH"])
    assert result["PRELAUNCH"].staleness == "fresh"
    assert result["PRELAUNCH"].fundamentals is not None
    assert result["PRELAUNCH"].fundamentals.pe_ratio is None
    assert result["PRELAUNCH"].fundamentals.eps == Decimal("5.0")
    assert result["PRELAUNCH"].fundamentals.market_cap == Decimal("1000000000")


async def test_inf_fundamentals_are_guarded_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini review — Inf / -Inf floats from yfinance must also map to None
    (not Decimal('Infinity') / Decimal('-Infinity'))."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _InfFundamentalsTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["EXOTIC"])
    assert result["EXOTIC"].staleness == "fresh"
    assert result["EXOTIC"].fundamentals is not None
    assert result["EXOTIC"].fundamentals.pe_ratio is None
    assert result["EXOTIC"].fundamentals.eps is None
    assert result["EXOTIC"].fundamentals.market_cap == Decimal("1000000000")


# --------- D-19 never-raise (Pitfall 1 + generic exception) ---------


async def test_get_prices_fetch_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall 1 — KeyError('currentTradingPeriod') on fast_info.last_price
    must NOT escape the provider. Must return fetch_failed slice."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _KeyErrorTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["ZZZZNOTREAL"])
    assert result["ZZZZNOTREAL"].staleness == "fetch_failed"
    assert result["ZZZZNOTREAL"].price is None
    assert result["ZZZZNOTREAL"].volume is None
    assert result["ZZZZNOTREAL"].source == "yfinance"


async def test_get_prices_generic_exception_returns_fetch_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-19 — any exception (not just Pitfall 1) converts to fetch_failed slice."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _ExplodingTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["ANY"])
    assert result["ANY"].staleness == "fetch_failed"


# --------- Edge cases (Pitfall 9 empty, duplicate tickers) ---------


async def test_empty_ticker_list_returns_empty_dict() -> None:
    """Pitfall 9 — empty list must not call asyncio.gather on an empty spread."""
    provider = YFinanceMarketDataProvider()
    assert await provider.get_prices([]) == {}
    assert await provider.get_fundamentals([]) == {}
    assert await provider.get_volume([]) == {}


async def test_duplicate_tickers_collapse_to_single_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matches FakeMarketDataProvider duplicate-handling semantics."""
    monkeypatch.setattr("alphaswarm.ingestion.yfinance_provider.yf.Ticker", _FakeTicker)
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL", "AAPL", "AAPL"])
    assert set(result.keys()) == {"AAPL"}


# --------- Module-level meta checks ---------


def test_yfinance_provider_module_imports_yfinance_but_not_other_network_libs() -> None:
    """yfinance_provider.py may import yfinance (its whole point) but must not
    reach for httpx/feedparser/requests — those belong to Plan 02 / elsewhere."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/yfinance_provider.py"
    content = src.read_text()
    assert "import yfinance" in content
    for banned in ("import httpx", "from httpx", "import feedparser", "from feedparser"):
        assert banned not in content, f"yfinance_provider.py must not contain '{banned}'"


def test_yfinance_provider_module_uses_fetch_failed_helper() -> None:
    """Pattern 3 — failure slices constructed via the shared helper, not hand-rolled."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/yfinance_provider.py"
    content = src.read_text()
    assert "from alphaswarm.ingestion.providers import _fetch_failed_market_slice" in content
    assert "_fetch_failed_market_slice(ticker, _SOURCE)" in content


def test_yfinance_provider_module_guards_nan_inf() -> None:
    """Gemini review invariant — _decimal_or_none must guard NaN/Inf floats."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/yfinance_provider.py"
    content = src.read_text()
    assert "import math" in content
    assert "math.isnan" in content
    assert "math.isinf" in content
