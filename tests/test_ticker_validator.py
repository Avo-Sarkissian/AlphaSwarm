"""Unit tests for SEC ticker validator module (TICK-02).

Tests cover:
- _load_ticker_set_from_file: JSON parse to uppercase set
- validate function: O(1) set lookup with case normalization
- ensure_sec_data: skip download if file exists, download if missing
- get_ticker_validator: lazy-load caching, callable return
- _download_sec_tickers: User-Agent header, atomic write (tmp + rename)
- CDN-unreachable fallback: ConnectError/TimeoutException -> returns None
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import alphaswarm.ticker_validator as tv
from alphaswarm.ticker_validator import (
    SEC_TICKERS_URL,
    SEC_USER_AGENT,
    _load_ticker_set_from_file,
    ensure_sec_data,
    get_ticker_validator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SEC_JSON = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "2": {"cik_str": 1318605, "ticker": "TSLA", "title": "TESLA INC"},
}


@pytest.fixture()
def sec_json_file(tmp_path: Path) -> Path:
    """Create a temporary SEC JSON file with known contents."""
    path = tmp_path / "sec_tickers.json"
    path.write_text(json.dumps(SAMPLE_SEC_JSON))
    return path


@pytest.fixture(autouse=True)
def reset_ticker_cache():
    """Reset module-level _ticker_set cache before and after each test."""
    tv._ticker_set = None
    yield
    tv._ticker_set = None


# ---------------------------------------------------------------------------
# _load_ticker_set_from_file tests
# ---------------------------------------------------------------------------


def test_load_ticker_set_returns_expected_symbols(sec_json_file: Path) -> None:
    """_load_ticker_set_from_file returns set with correct symbols."""
    result = _load_ticker_set_from_file(sec_json_file)
    assert result == {"AAPL", "MSFT", "TSLA"}


def test_load_ticker_set_uppercase_conversion(tmp_path: Path) -> None:
    """_load_ticker_set_from_file uppercases symbols even if JSON has lowercase."""
    data = {"0": {"cik_str": 1, "ticker": "aapl", "title": "Apple"}}
    path = tmp_path / "sec_tickers.json"
    path.write_text(json.dumps(data))
    result = _load_ticker_set_from_file(path)
    assert "AAPL" in result
    assert "aapl" not in result


# ---------------------------------------------------------------------------
# validate function (closure from get_ticker_validator) tests
# ---------------------------------------------------------------------------


async def test_validate_returns_true_for_valid_symbol(sec_json_file: Path) -> None:
    """validate returns True for 'AAPL' when AAPL is in the set."""
    validator = await get_ticker_validator(data_dir=sec_json_file.parent)
    assert validator is not None
    assert validator("AAPL") is True


async def test_validate_case_insensitive(sec_json_file: Path) -> None:
    """validate returns True for 'aapl' (lowercase) when AAPL is in the set."""
    validator = await get_ticker_validator(data_dir=sec_json_file.parent)
    assert validator is not None
    assert validator("aapl") is True


async def test_validate_returns_false_for_unknown_symbol(sec_json_file: Path) -> None:
    """validate returns False for 'XYZFAKE' not in the SEC set."""
    validator = await get_ticker_validator(data_dir=sec_json_file.parent)
    assert validator is not None
    assert validator("XYZFAKE") is False


# ---------------------------------------------------------------------------
# ensure_sec_data tests
# ---------------------------------------------------------------------------


async def test_ensure_sec_data_no_download_if_file_exists(sec_json_file: Path) -> None:
    """ensure_sec_data does not download if the file already exists."""
    with patch("alphaswarm.ticker_validator._download_sec_tickers") as mock_download:
        result = await ensure_sec_data(data_dir=sec_json_file.parent)
        mock_download.assert_not_called()
    assert result == sec_json_file


async def test_ensure_sec_data_downloads_if_missing(tmp_path: Path) -> None:
    """ensure_sec_data triggers download when file is absent."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    async def fake_download(dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(SAMPLE_SEC_JSON))

    with patch("alphaswarm.ticker_validator._download_sec_tickers", side_effect=fake_download):
        result = await ensure_sec_data(data_dir=empty_dir)

    assert result.exists()


# ---------------------------------------------------------------------------
# get_ticker_validator tests
# ---------------------------------------------------------------------------


async def test_get_ticker_validator_returns_callable(sec_json_file: Path) -> None:
    """get_ticker_validator returns a callable."""
    validator = await get_ticker_validator(data_dir=sec_json_file.parent)
    assert callable(validator)


async def test_get_ticker_validator_caches_on_second_call(sec_json_file: Path) -> None:
    """Second call to get_ticker_validator does not reload file (uses module cache)."""
    with patch("alphaswarm.ticker_validator._load_ticker_set_from_file", wraps=_load_ticker_set_from_file) as mock_load:
        await get_ticker_validator(data_dir=sec_json_file.parent)
        await get_ticker_validator(data_dir=sec_json_file.parent)
        assert mock_load.call_count == 1, "File should only be loaded once (cached)"


# ---------------------------------------------------------------------------
# _download_sec_tickers tests
# ---------------------------------------------------------------------------


async def test_download_uses_correct_user_agent(tmp_path: Path) -> None:
    """_download_sec_tickers sends the correct User-Agent header."""
    dest = tmp_path / "sec_tickers.json"
    fake_content = json.dumps(SAMPLE_SEC_JSON).encode()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = fake_content

    mock_get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from alphaswarm.ticker_validator import _download_sec_tickers
        await _download_sec_tickers(dest)

    mock_get.assert_called_once_with(
        SEC_TICKERS_URL,
        headers={"User-Agent": SEC_USER_AGENT},
        timeout=30.0,
    )


async def test_download_uses_atomic_write_tmp_then_rename(tmp_path: Path) -> None:
    """_download_sec_tickers writes to a .tmp file then renames (atomic write)."""
    dest = tmp_path / "sec_tickers.json"
    fake_content = json.dumps(SAMPLE_SEC_JSON).encode()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = fake_content

    mock_get = AsyncMock(return_value=mock_response)

    written_paths: list[str] = []
    original_write_bytes = Path.write_bytes

    def tracking_write_bytes(self: Path, data: bytes) -> int:
        written_paths.append(str(self))
        return original_write_bytes(self, data)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(Path, "write_bytes", tracking_write_bytes):
            from alphaswarm.ticker_validator import _download_sec_tickers
            await _download_sec_tickers(dest)

    # Should have written to a .tmp path, not the final destination
    assert any(".tmp" in p for p in written_paths), f"Expected write to .tmp, got: {written_paths}"
    # Final file should exist after rename
    assert dest.exists()


# ---------------------------------------------------------------------------
# CDN-unreachable fallback tests
# ---------------------------------------------------------------------------


async def test_get_ticker_validator_returns_none_on_connect_error(tmp_path: Path) -> None:
    """get_ticker_validator returns None when SEC CDN is unreachable (ConnectError)."""
    empty_dir = tmp_path / "no_data"
    empty_dir.mkdir()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_ticker_validator(data_dir=empty_dir)

    assert result is None


async def test_get_ticker_validator_returns_none_on_timeout(tmp_path: Path) -> None:
    """get_ticker_validator returns None when SEC CDN times out (TimeoutException)."""
    empty_dir = tmp_path / "no_data2"
    empty_dir.mkdir()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_ticker_validator(data_dir=empty_dir)

    assert result is None


async def test_get_ticker_validator_logs_warning_with_manual_download_on_cdn_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """get_ticker_validator logs a warning containing 'manually download' on CDN failure."""
    import logging

    empty_dir = tmp_path / "no_data3"
    empty_dir.mkdir()

    log_records: list[str] = []

    class CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_records.append(self.format(record))

    handler = CapturingHandler()
    # structlog sends through stdlib logging when not configured otherwise
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.WARNING)

    try:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch.object(tv.logger, "warning") as mock_warning:
                result = await get_ticker_validator(data_dir=empty_dir)

        # Verify the warning was emitted at least once mentioning manual download
        assert result is None
        # Check structlog warning calls
        all_calls = str(mock_warning.call_args_list)
        assert "manually download" in all_calls.lower() or any(
            "manually download" in str(call).lower()
            for call in mock_warning.call_args_list
        ), f"Expected 'manually download' in warning calls: {mock_warning.call_args_list}"
    finally:
        root_logger.removeHandler(handler)


async def test_download_sec_tickers_catches_connect_error_and_reraises(tmp_path: Path) -> None:
    """_download_sec_tickers catches ConnectError, logs warning, and re-raises."""
    dest = tmp_path / "sec_tickers.json"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from alphaswarm.ticker_validator import _download_sec_tickers
        with pytest.raises(httpx.ConnectError):
            await _download_sec_tickers(dest)


async def test_download_sec_tickers_catches_timeout_and_reraises(tmp_path: Path) -> None:
    """_download_sec_tickers catches TimeoutException, logs warning, and re-raises."""
    dest = tmp_path / "sec_tickers.json"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from alphaswarm.ticker_validator import _download_sec_tickers
        with pytest.raises(httpx.TimeoutException):
            await _download_sec_tickers(dest)
