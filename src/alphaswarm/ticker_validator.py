"""SEC ticker symbol validation for AlphaSwarm.

Loads company_tickers.json from SEC CDN (one-time download),
caches as in-memory set for O(1) symbol lookup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import structlog

logger = structlog.get_logger(component="ticker_validator")

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "AlphaSwarm admin@alphaswarm.local"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_FILENAME = "sec_tickers.json"

# Module-level cache (lazy-loaded, process-lifetime)
_ticker_set: set[str] | None = None


def _load_ticker_set_from_file(path: Path) -> set[str]:
    """Parse SEC JSON into uppercase ticker symbol set."""
    with path.open() as f:
        data = json.load(f)
    return {entry["ticker"].upper() for entry in data.values()}


async def _download_sec_tickers(dest: Path) -> None:
    """Download company_tickers.json from SEC CDN.

    Uses atomic write (temp file + rename) to prevent partial file on interrupt.

    Raises:
        httpx.ConnectError: If SEC CDN is unreachable (caught by caller).
        httpx.TimeoutException: If SEC CDN request times out (caught by caller).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(".json.tmp")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                SEC_TICKERS_URL,
                headers={"User-Agent": SEC_USER_AGENT},
                timeout=30.0,
            )
            response.raise_for_status()
            tmp_path.write_bytes(response.content)
        tmp_path.rename(dest)
        logger.info("sec_tickers_downloaded", path=str(dest), size_bytes=dest.stat().st_size)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        # Clean up partial temp file if it exists
        tmp_path.unlink(missing_ok=True)
        logger.warning(
            "sec_cdn_unreachable",
            url=SEC_TICKERS_URL,
            error=str(exc),
            hint="Manually download from https://www.sec.gov/files/company_tickers.json and place at data/sec_tickers.json",
        )
        raise


async def ensure_sec_data(data_dir: Path | None = None) -> Path:
    """Ensure SEC tickers file exists on disk. Download if missing.

    Args:
        data_dir: Override for the data directory. Defaults to project-root data/.

    Returns:
        Path to the SEC tickers JSON file.
    """
    directory = data_dir or DEFAULT_DATA_DIR
    path = directory / DEFAULT_FILENAME
    if not path.exists():
        logger.info("sec_tickers_missing_downloading", path=str(path))
        await _download_sec_tickers(path)
    return path


async def get_ticker_validator(
    data_dir: Path | None = None,
) -> Callable[[str], bool] | None:
    """Return a sync validation function: symbol -> bool, or None if SEC data unavailable.

    Downloads SEC data if missing. Caches ticker set in module-level variable.
    Thread-safe for read after initial load (set is immutable once assigned).

    Returns None (instead of crashing) when the SEC CDN is unreachable and no
    local SEC file exists. The caller should pass None to parse_seed_event's
    ticker_validator parameter, which skips validation and keeps all extracted
    tickers. (Addresses review concern: SEC CDN unreachable on first run.)

    Args:
        data_dir: Override for the data directory (useful for testing).

    Returns:
        A function that takes a ticker symbol string and returns True if valid,
        or None if SEC data could not be loaded.
    """
    global _ticker_set
    if _ticker_set is None:
        try:
            path = await ensure_sec_data(data_dir)
            _ticker_set = _load_ticker_set_from_file(path)
            logger.info("sec_tickers_loaded", count=len(_ticker_set))
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(
                "sec_validation_unavailable",
                reason="SEC CDN unreachable and no local data file found",
                impact="Ticker validation will be skipped -- all extracted tickers will be kept",
                action="To enable validation, manually download from https://www.sec.gov/files/company_tickers.json and place at data/sec_tickers.json",
            )
            return None

    def validate(symbol: str) -> bool:
        return symbol.upper() in _ticker_set  # type: ignore[union-attr]

    return validate
