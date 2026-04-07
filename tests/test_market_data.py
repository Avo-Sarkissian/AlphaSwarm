"""Tests for market data pipeline (Phase 17: DATA-01, DATA-02, DATA-04).

Coverage:
  - DATA-01: MarketDataSnapshot model contract and yfinance fetch behavior
  - DATA-02: Alpha Vantage fallback and degraded snapshot logic
  - DATA-04: Disk cache write/read/TTL/logging behavior
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import MarketDataSnapshot


# ---------------------------------------------------------------------------
# DATA-01: MarketDataSnapshot model tests (run immediately — no market_data.py)
# ---------------------------------------------------------------------------


class TestMarketDataSnapshotModel:
    """DATA-01: Validate the MarketDataSnapshot Pydantic model contract."""

    def test_snapshot_model_valid(self) -> None:
        """Full snapshot with all fields populated is accepted without error."""
        s = MarketDataSnapshot(
            symbol="AAPL",
            company_name="Apple Inc",
            pe_ratio=28.5,
            market_cap=3_000_000_000_000,
        )
        assert s.symbol == "AAPL"
        assert s.company_name == "Apple Inc"
        assert s.pe_ratio == 28.5
        assert s.market_cap == 3_000_000_000_000
        assert s.is_degraded is False
        assert s.headlines == []
        assert s.price_history == []

    def test_snapshot_model_degraded(self) -> None:
        """Degraded snapshot with is_degraded=True has empty price_history and None fundamentals."""
        s = MarketDataSnapshot(symbol="AAPL", is_degraded=True)
        assert s.price_history == []
        assert s.pe_ratio is None
        assert s.market_cap is None
        assert s.is_degraded is True

    def test_snapshot_model_frozen(self) -> None:
        """Frozen model rejects attribute assignment with TypeError or ValidationError."""
        s = MarketDataSnapshot(symbol="AAPL")
        with pytest.raises((TypeError, Exception)):
            s.symbol = "X"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DATA-01: yfinance fetch tests (stub until market_data.py exists in Plan 02)
# ---------------------------------------------------------------------------


class TestYfinanceFetch:
    """DATA-01: Verify yfinance-backed fetch returns valid MarketDataSnapshot.

    Plan 02 will un-stub these by implementing:
      - _fetch_single_ticker(symbol, settings) -> MarketDataSnapshot
      - fetch_market_data(tickers, settings) -> dict[str, MarketDataSnapshot]
    Mock strategy: patch asyncio.to_thread to return a pre-built yfinance dict.
    """

    async def test_fetch_yfinance_returns_snapshot(self) -> None:
        """Mock asyncio.to_thread returns dict; snapshot has non-None pe_ratio and non-empty price_history."""
        pytest.skip("market_data.py not yet implemented")

    async def test_parallel_fetch_all_tickers(self) -> None:
        """Mock _fetch_single_ticker for 3 tickers; fetch_market_data returns dict with 3 keys."""
        pytest.skip("market_data.py not yet implemented")


# ---------------------------------------------------------------------------
# DATA-02: Fallback and degradation tests (stub until market_data.py exists)
# ---------------------------------------------------------------------------


class TestFallbackDegradation:
    """DATA-02: Alpha Vantage fallback and graceful degradation.

    Plan 02 will un-stub these by implementing:
      - AV fallback path triggered on yfinance Exception
      - Degraded snapshot returned when both yfinance and AV fail
      - AV skip path when alpha_vantage_api_key is None
    Mock strategy: patch yfinance.Ticker and httpx.AsyncClient.get.
    """

    async def test_av_fallback_on_yfinance_failure(self) -> None:
        """Mock yfinance to raise Exception; mock AV httpx to return valid data; snapshot has pe_ratio from AV."""
        pytest.skip("market_data.py not yet implemented")

    async def test_degraded_snapshot_both_fail(self) -> None:
        """Mock both yfinance and AV to raise; returned snapshot.is_degraded is True."""
        pytest.skip("market_data.py not yet implemented")

    async def test_av_skipped_no_key(self) -> None:
        """When alpha_vantage_api_key is None and yfinance fails, AV httpx is never called; snapshot is degraded."""
        pytest.skip("market_data.py not yet implemented")


# ---------------------------------------------------------------------------
# DATA-04: Disk cache tests (stub until market_data.py exists in Plan 03)
# ---------------------------------------------------------------------------


class TestDiskCache:
    """DATA-04: Disk cache write/read/TTL/logging behavior.

    Plan 03 will un-stub these by implementing:
      - _write_cache(snapshot, cache_dir) -> None
      - _read_cache(symbol, cache_dir, ttl_seconds) -> MarketDataSnapshot | None
    Cache format: JSON at data/market_cache/{SYMBOL}.json with "cached_at" ISO key.
    TTL: configurable, default 3600 seconds (1 hour).
    """

    async def test_cache_write_creates_file(self, tmp_path: Path) -> None:
        """After _write_cache, file exists at {cache_dir}/{SYMBOL}.json with 'cached_at' key."""
        pytest.skip("market_data.py not yet implemented")

    async def test_cache_hit_within_ttl(self, tmp_path: Path) -> None:
        """Write cache, then _read_cache returns non-None MarketDataSnapshot within TTL."""
        pytest.skip("market_data.py not yet implemented")

    async def test_cache_miss_expired_ttl(self, tmp_path: Path) -> None:
        """Write cache with old cached_at timestamp; _read_cache returns None (TTL expired)."""
        pytest.skip("market_data.py not yet implemented")

    async def test_cache_hit_logged(self, tmp_path: Path) -> None:
        """On cache hit, structlog emits event with 'cache_hit' at INFO level."""
        pytest.skip("market_data.py not yet implemented")
