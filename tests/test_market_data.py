"""Tests for market data pipeline (Phase 17: DATA-01, DATA-02, DATA-04).

Coverage:
  - DATA-01: MarketDataSnapshot model contract and yfinance fetch behavior
  - DATA-02: Alpha Vantage fallback and degraded snapshot logic
  - DATA-04: Disk cache write/read/TTL/logging behavior
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing

from alphaswarm.types import ExtractedTicker, MarketDataSnapshot

# ---------------------------------------------------------------------------
# Shared yfinance dict fixture used across DATA-01 tests
# ---------------------------------------------------------------------------

_YFINANCE_DATA = {
    "price_history": [
        {
            "date": "2025-01-01T00:00:00-05:00",
            "open": 150.0,
            "high": 155.0,
            "low": 149.0,
            "close": 153.0,
            "volume": 1_000_000,
        }
    ],
    "pe_ratio": 28.5,
    "market_cap": 3_000_000_000_000,
    "fifty_two_week_high": 200.0,
    "fifty_two_week_low": 120.0,
    "eps_trailing": 6.5,
    "revenue_ttm": 400_000_000_000,
    "gross_margin_pct": 0.45,
    "debt_to_equity": 1.5,
    "company_name": "Apple Inc",
    "earnings_surprise_pct": 5.2,
    "next_earnings_date": "2025-04-15T00:00:00-04:00",
    "last_close": 153.0,
    "price_change_30d_pct": 2.5,
    "price_change_90d_pct": 8.1,
    "avg_volume_30d": 950_000.0,
}

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
# DATA-01: yfinance fetch tests
# ---------------------------------------------------------------------------


class TestYfinanceFetch:
    """DATA-01: Verify yfinance-backed fetch returns valid MarketDataSnapshot."""

    async def test_fetch_yfinance_returns_snapshot(self, tmp_path: Path) -> None:
        """Mock _fetch_yfinance_sync returns dict; snapshot has non-None pe_ratio and non-empty price_history."""
        from alphaswarm.market_data import _fetch_single_ticker

        with patch(
            "alphaswarm.market_data._fetch_yfinance_sync",
            return_value=dict(_YFINANCE_DATA),
        ):
            snapshot = await _fetch_single_ticker(
                "AAPL", "Apple Inc", av_key=None, cache_dir=tmp_path
            )

        assert snapshot.pe_ratio == 28.5
        assert len(snapshot.price_history) == 1
        assert snapshot.is_degraded is False
        assert snapshot.symbol == "AAPL"
        assert snapshot.company_name == "Apple Inc"

    async def test_parallel_fetch_all_tickers(self, tmp_path: Path) -> None:
        """Mock _fetch_single_ticker for 3 tickers; fetch_market_data returns dict with 3 keys."""
        from alphaswarm.market_data import fetch_market_data

        tickers = [
            ExtractedTicker(symbol="AAPL", company_name="Apple Inc", relevance=0.9),
            ExtractedTicker(symbol="TSLA", company_name="Tesla Inc", relevance=0.8),
            ExtractedTicker(symbol="MSFT", company_name="Microsoft Corp", relevance=0.7),
        ]

        async def _mock_fetch(symbol: str, company_name: str, av_key: str | None, cache_dir: Path | None) -> MarketDataSnapshot:
            return MarketDataSnapshot(symbol=symbol, company_name=company_name)

        with patch(
            "alphaswarm.market_data._fetch_single_ticker",
            side_effect=_mock_fetch,
        ):
            result = await fetch_market_data(tickers, cache_dir=tmp_path)

        assert set(result.keys()) == {"AAPL", "TSLA", "MSFT"}
        assert result["AAPL"].symbol == "AAPL"
        assert result["TSLA"].symbol == "TSLA"
        assert result["MSFT"].symbol == "MSFT"


# ---------------------------------------------------------------------------
# DATA-02: Fallback and degradation tests
# ---------------------------------------------------------------------------


class TestFallbackDegradation:
    """DATA-02: Alpha Vantage fallback and graceful degradation."""

    async def test_av_fallback_on_yfinance_failure(self, tmp_path: Path) -> None:
        """Mock yfinance to raise; mock AV httpx returns valid data; snapshot not degraded with pe_ratio from AV."""
        from alphaswarm.market_data import _fetch_single_ticker

        av_quote_json = {
            "Global Quote": {
                "01. symbol": "AAPL",
                "05. price": "153.00",
                "06. volume": "1000000",
            }
        }
        av_overview_json = {
            "Name": "Apple Inc",
            "PERatio": "28.5",
            "MarketCapitalization": "3000000000000",
            "52WeekHigh": "200.0",
            "52WeekLow": "120.0",
            "EPS": "6.5",
            "RevenueTTM": "400000000000",
        }

        mock_quote_resp = MagicMock()
        mock_quote_resp.json.return_value = av_quote_json

        mock_overview_resp = MagicMock()
        mock_overview_resp.json.return_value = av_overview_json

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_quote_resp, mock_overview_resp]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "alphaswarm.market_data._fetch_yfinance_sync",
                side_effect=Exception("yfinance down"),
            ),
            patch("alphaswarm.market_data.httpx.AsyncClient", return_value=mock_client),
        ):
            snapshot = await _fetch_single_ticker(
                "AAPL", "Apple Inc", av_key="test_key", cache_dir=tmp_path
            )

        assert snapshot.is_degraded is False
        assert snapshot.pe_ratio is not None
        assert snapshot.pe_ratio == 28.5

    async def test_degraded_snapshot_both_fail(self, tmp_path: Path) -> None:
        """Mock both yfinance and AV to raise; returned snapshot.is_degraded is True."""
        from alphaswarm.market_data import _fetch_single_ticker

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("httpx connect error"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "alphaswarm.market_data._fetch_yfinance_sync",
                side_effect=Exception("yfinance down"),
            ),
            patch("alphaswarm.market_data.httpx.AsyncClient", return_value=mock_client),
        ):
            snapshot = await _fetch_single_ticker(
                "AAPL", "Apple Inc", av_key="test_key", cache_dir=tmp_path
            )

        assert snapshot.is_degraded is True
        assert snapshot.symbol == "AAPL"

    async def test_av_skipped_no_key(self, tmp_path: Path) -> None:
        """When av_key is None and yfinance fails, AV httpx is never called; snapshot is degraded."""
        from alphaswarm.market_data import _fetch_single_ticker

        with (
            patch(
                "alphaswarm.market_data._fetch_yfinance_sync",
                side_effect=Exception("yfinance down"),
            ),
            patch("alphaswarm.market_data.httpx.AsyncClient") as mock_client_cls,
        ):
            snapshot = await _fetch_single_ticker(
                "AAPL", "Apple Inc", av_key=None, cache_dir=tmp_path
            )
            # httpx.AsyncClient should never be instantiated when av_key is None
            mock_client_cls.assert_not_called()

        assert snapshot.is_degraded is True


# ---------------------------------------------------------------------------
# DATA-04: Disk cache tests
# ---------------------------------------------------------------------------


class TestDiskCache:
    """DATA-04: Disk cache write/read/TTL/logging behavior."""

    async def test_cache_write_creates_file(self, tmp_path: Path) -> None:
        """After _write_cache, file exists at {cache_dir}/{SYMBOL}.json with 'cached_at' and 'snapshot' keys."""
        from alphaswarm.market_data import _write_cache

        snapshot = MarketDataSnapshot(symbol="AAPL", company_name="Apple")
        await _write_cache("AAPL", snapshot, cache_dir=tmp_path)

        cache_file = tmp_path / "AAPL.json"
        assert cache_file.exists()

        data = json.loads(cache_file.read_text())
        assert "cached_at" in data
        assert "snapshot" in data
        assert data["snapshot"]["symbol"] == "AAPL"

    async def test_cache_hit_within_ttl(self, tmp_path: Path) -> None:
        """Write cache, then _read_cache returns non-None MarketDataSnapshot within TTL."""
        from alphaswarm.market_data import _read_cache, _write_cache

        snapshot = MarketDataSnapshot(symbol="AAPL", company_name="Apple")
        await _write_cache("AAPL", snapshot, cache_dir=tmp_path)

        result = await _read_cache("AAPL", cache_dir=tmp_path)
        assert result is not None
        assert result.symbol == "AAPL"

    async def test_cache_miss_expired_ttl(self, tmp_path: Path) -> None:
        """Write a cache file with cached_at 2 hours ago; _read_cache returns None (TTL expired)."""
        from alphaswarm.market_data import _read_cache

        snapshot = MarketDataSnapshot(symbol="AAPL", company_name="Apple")
        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        payload = {
            "cached_at": two_hours_ago.isoformat(),
            "snapshot": snapshot.model_dump(mode="json"),
        }
        (tmp_path / "AAPL.json").write_text(json.dumps(payload))

        result = await _read_cache("AAPL", cache_dir=tmp_path)
        assert result is None

    async def test_cache_hit_logged(self, tmp_path: Path) -> None:
        """On cache hit, structlog emits event with event='cache_hit' and ticker='AAPL'."""
        from alphaswarm.market_data import _fetch_single_ticker, _write_cache

        # Prime the cache
        snapshot = MarketDataSnapshot(symbol="AAPL", company_name="Apple")
        await _write_cache("AAPL", snapshot, cache_dir=tmp_path)

        with structlog.testing.capture_logs() as cap:
            result = await _fetch_single_ticker(
                "AAPL", "Apple Inc", av_key=None, cache_dir=tmp_path
            )

        assert result is not None
        assert result.symbol == "AAPL"
        cache_hit_events = [e for e in cap if e.get("event") == "cache_hit"]
        assert len(cache_hit_events) >= 1
        assert cache_hit_events[0]["ticker"] == "AAPL"
