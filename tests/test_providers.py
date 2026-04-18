"""ISOL-05 tests: Protocol conformance + FakeMarketDataProvider/FakeNewsProvider behavior.

pytest-asyncio asyncio_mode='auto' is configured project-wide — async tests
do not need @pytest.mark.asyncio decoration.

REVIEW REVISION (2026-04-18):
- Added explicit async-signature tests (inspect.iscoroutinefunction)
- Added empty-input, duplicate-ticker, and exception-as-failed-slice tests
- Added typed-literal StalenessState assertion
"""

from __future__ import annotations

import inspect
import pathlib
import typing
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alphaswarm.ingestion import (
    FakeMarketDataProvider,
    FakeNewsProvider,
    MarketDataProvider,
    MarketSlice,
    NewsProvider,
    NewsSlice,
    StalenessState,
)


# --------- Structural (mypy-enforced) conformance ---------


async def _market_consumer(p: MarketDataProvider) -> list[str]:
    """mypy conformance probe — if FakeMarketDataProvider drifts, this fails to type-check."""
    result = await p.get_prices(["AAPL"])
    return list(result.keys())


async def _news_consumer(p: NewsProvider) -> list[str]:
    result = await p.get_headlines(["AAPL"], max_age_hours=48)
    return list(result.keys())


async def test_fake_market_data_provider_structurally_conforms() -> None:
    fake = FakeMarketDataProvider()
    keys = await _market_consumer(fake)
    assert keys == ["AAPL"]


async def test_fake_news_provider_structurally_conforms() -> None:
    fake = FakeNewsProvider()
    keys = await _news_consumer(fake)
    assert keys == ["AAPL"]


# --------- Async-signature enforcement (REVIEW MEDIUM — Gemini/Codex) ---------


def test_market_protocol_methods_are_async_def() -> None:
    """Every MarketDataProvider method must be `async def` — sync would block
    the event loop under Phase 38's 100-ticker concurrent aggregation."""
    for method_name in ("get_prices", "get_fundamentals", "get_volume"):
        method = getattr(MarketDataProvider, method_name)
        assert inspect.iscoroutinefunction(method), (
            f"MarketDataProvider.{method_name} must be `async def`"
        )


def test_news_protocol_method_is_async_def() -> None:
    assert inspect.iscoroutinefunction(NewsProvider.get_headlines), (
        "NewsProvider.get_headlines must be `async def`"
    )


def test_fake_market_methods_are_async_def() -> None:
    fake = FakeMarketDataProvider()
    for method_name in ("get_prices", "get_fundamentals", "get_volume"):
        method = getattr(fake, method_name)
        assert inspect.iscoroutinefunction(method), (
            f"FakeMarketDataProvider.{method_name} must be `async def`"
        )


def test_fake_news_methods_are_async_def() -> None:
    fake = FakeNewsProvider()
    assert inspect.iscoroutinefunction(fake.get_headlines)


# --------- FakeMarketDataProvider behavior ---------


async def test_fake_market_returns_fixture_for_known_ticker() -> None:
    fixture = MarketSlice(
        ticker="AAPL",
        price=Decimal("185.50"),
        fetched_at=datetime.now(UTC),
        source="test",
    )
    fake = FakeMarketDataProvider(fixtures={"AAPL": fixture})
    result = await fake.get_prices(["AAPL"])
    assert result["AAPL"].price == Decimal("185.50")
    assert result["AAPL"].staleness == "fresh"


async def test_fake_market_returns_fetch_failed_for_unknown_ticker() -> None:
    fake = FakeMarketDataProvider()
    result = await fake.get_prices(["UNKNOWN"])
    assert "UNKNOWN" in result
    assert result["UNKNOWN"].staleness == "fetch_failed"
    assert result["UNKNOWN"].price is None


async def test_fake_market_never_raises_on_unknown_ticker() -> None:
    fake = FakeMarketDataProvider()
    # Must not raise — D-19 contract
    _ = await fake.get_prices(["NOT_A_REAL_TICKER"])


# --------- Never-raise coverage expansion (REVIEW MEDIUM — Codex) ---------


async def test_fake_market_returns_empty_dict_for_empty_ticker_list() -> None:
    """D-19 never-raise contract holds for empty inputs — aggregation loops
    with no tickers must not trip a KeyError/ValueError (REVIEW MEDIUM)."""
    fake = FakeMarketDataProvider()
    result = await fake.get_prices([])
    assert result == {}


async def test_fake_market_returns_single_key_for_duplicate_tickers() -> None:
    """Duplicate tickers in a batch collapse to one entry via dict-comprehension
    semantics. This is the documented contract — callers upstream are expected
    to de-duplicate, but providers MUST be idempotent and non-raising here
    (REVIEW MEDIUM — Codex duplicate handling)."""
    fake = FakeMarketDataProvider()
    result = await fake.get_prices(["AAPL", "AAPL", "AAPL"])
    assert set(result.keys()) == {"AAPL"}
    assert result["AAPL"].staleness == "fetch_failed"  # no fixture configured


async def test_fake_market_returns_fetch_failed_when_fixture_source_raises() -> None:
    """D-19 never-raise contract holds even when a programmer-supplied
    fixture_source callback raises internally — the exception is converted
    to a fetch_failed slice (REVIEW MEDIUM — Codex 'exceptions-as-failed-slices')."""

    def bad_source(_ticker: str) -> MarketSlice:
        raise RuntimeError("simulated fixture-source failure")

    fake = FakeMarketDataProvider(fixture_source=bad_source)
    result = await fake.get_prices(["AAPL", "MSFT"])
    assert result["AAPL"].staleness == "fetch_failed"
    assert result["MSFT"].staleness == "fetch_failed"
    assert result["AAPL"].price is None


async def test_fake_market_supports_sentinel_ticker() -> None:
    fixture = MarketSlice(
        ticker="SNTL_CANARY_TICKER",
        price=Decimal("1.00"),
        fetched_at=datetime.now(UTC),
        source="canary",
    )
    fake = FakeMarketDataProvider(fixtures={"SNTL_CANARY_TICKER": fixture})
    result = await fake.get_prices(["SNTL_CANARY_TICKER"])
    assert result["SNTL_CANARY_TICKER"].ticker == "SNTL_CANARY_TICKER"


async def test_fake_market_batch_returns_entry_per_input() -> None:
    fake = FakeMarketDataProvider()
    result = await fake.get_prices(["A", "B", "C"])
    assert set(result.keys()) == {"A", "B", "C"}


async def test_fake_market_get_fundamentals_and_volume_implemented() -> None:
    fake = FakeMarketDataProvider()
    f = await fake.get_fundamentals(["AAPL"])
    v = await fake.get_volume(["AAPL"])
    assert "AAPL" in f and "AAPL" in v


# --------- FakeNewsProvider behavior ---------


async def test_fake_news_returns_fixture_for_known_entity() -> None:
    fixture = NewsSlice(
        entity="AAPL",
        headlines=("Apple beats earnings",),
        fetched_at=datetime.now(UTC),
        source="test",
    )
    fake = FakeNewsProvider(fixtures={"AAPL": fixture})
    result = await fake.get_headlines(["AAPL"])
    assert result["AAPL"].headlines == ("Apple beats earnings",)


async def test_fake_news_returns_fetch_failed_for_unknown_entity() -> None:
    fake = FakeNewsProvider()
    result = await fake.get_headlines(["UNKNOWN"])
    assert result["UNKNOWN"].staleness == "fetch_failed"
    assert result["UNKNOWN"].headlines == ()


async def test_fake_news_returns_empty_dict_for_empty_entity_list() -> None:
    """REVIEW MEDIUM — empty-input never-raise coverage for news path."""
    fake = FakeNewsProvider()
    result = await fake.get_headlines([])
    assert result == {}


async def test_fake_news_accepts_max_age_hours_keyword() -> None:
    fake = FakeNewsProvider()
    result = await fake.get_headlines(["AAPL"], max_age_hours=24)
    assert "AAPL" in result


# --------- StalenessState typed-literal enforcement (REVIEW MEDIUM — Codex) ---------


def test_staleness_state_literal_set() -> None:
    """StalenessState MUST be the typed Literal['fresh','stale','fetch_failed']
    alias — not an unconstrained str. Guards against downstream drift."""
    args = typing.get_args(StalenessState)
    assert set(args) == {"fresh", "stale", "fetch_failed"}


async def test_fake_market_staleness_values_belong_to_literal_set() -> None:
    """Every staleness value returned by the fake must be a member of
    StalenessState — no accidental 'failed', 'error', 'fail' variants
    (REVIEW MEDIUM — Codex typed literal)."""
    valid = set(typing.get_args(StalenessState))
    fake = FakeMarketDataProvider()
    result = await fake.get_prices(["UNKNOWN_A", "UNKNOWN_B"])
    for slice_ in result.values():
        assert slice_.staleness in valid


async def test_fake_news_staleness_values_belong_to_literal_set() -> None:
    valid = set(typing.get_args(StalenessState))
    fake = FakeNewsProvider()
    result = await fake.get_headlines(["UNKNOWN_A", "UNKNOWN_B"])
    for slice_ in result.values():
        assert slice_.staleness in valid


# --------- Meta-test: no network library imports (Pitfall 5) ---------


def test_providers_module_has_no_network_imports() -> None:
    """providers.py must be pure in-memory — no yfinance/httpx/feedparser/requests/aiohttp."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/providers.py"
    content = src.read_text()
    forbidden = (
        "import yfinance",
        "from yfinance",
        "import httpx",
        "from httpx",
        "import feedparser",
        "import requests",
        "import aiohttp",
    )
    for banned in forbidden:
        assert banned not in content, f"providers.py must not contain '{banned}'"


def test_providers_module_has_no_sleep_calls() -> None:
    """Fakes must not simulate latency — keep tests fast and deterministic (Pitfall 5)."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/providers.py"
    content = src.read_text()
    assert "asyncio.sleep" not in content
    assert "time.sleep" not in content


def test_providers_module_has_no_runtime_checkable() -> None:
    """Protocols must not be @runtime_checkable (Pitfall 8 — no isinstance overhead)."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/providers.py"
    content = src.read_text()
    assert "@runtime_checkable" not in content


def test_providers_module_has_no_sync_get_methods() -> None:
    """REVIEW MEDIUM — no sync `def get_*` definitions allowed; all async."""
    import re

    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/providers.py"
    content = src.read_text()
    # Match leading-whitespace "def get_X(" but NOT "async def get_X("
    sync_defs = re.findall(r"^\s+def get_(prices|fundamentals|volume|headlines)\(", content, re.MULTILINE)
    assert sync_defs == [], f"Found sync provider methods (must be async): {sync_defs}"
