"""C-TEST-20: holdings test fixtures use only the reserved fictional tickers.

The owner's real positions must never appear in tests
(docs/DECISIONS.md#adr-holdings-isolation). This guard covers the ticker half of
that rule for the files listed in FICTIONAL_FIXTURE_FILES; quantities and cost
basis are checked by the owner-run scripts/privacy_scan.py.

Failure messages name line numbers only, never the offending token, so a
failing run cannot echo a real ticker into a terminal or CI log.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

RESERVED_TICKERS: frozenset[str] = frozenset({"ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX"})

FICTIONAL_FIXTURE_FILES: tuple[str, ...] = (
    "tests/test_holdings_loader.py",
    "tests/integration/test_holdings_route.py",
    "tests/test_holdings_validation.py",
    "tests/test_example_holdings.py",
    "examples/holdings.example.csv",
    "tests/test_portfolio_cache.py",
)

# A CSV data row inside a string literal: "<account>,<TICKER>,<qty>,..."
_CSV_ROW_TICKER = re.compile(r"[a-z_]+,([A-Z][A-Z0-9.\-]{0,9}),")
# A quoted all-caps token: ticker="ZZZT", ["ZZZT", "QQQX"], "QZZX" in tickers
_QUOTED_UPPER = re.compile(r"[\"']([A-Z]{1,6})[\"']")


def offending_lines(path: Path) -> list[int]:
    """Return 1-based line numbers that use a ticker outside RESERVED_TICKERS."""
    bad: list[int] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        tokens = set(_CSV_ROW_TICKER.findall(line)) | set(_QUOTED_UPPER.findall(line))
        if tokens - RESERVED_TICKERS:
            bad.append(lineno)
    return bad


@pytest.mark.parametrize("rel_path", FICTIONAL_FIXTURE_FILES)
def test_holdings_fixtures_use_only_reserved_tickers(rel_path: str) -> None:
    bad = offending_lines(ROOT / rel_path)
    assert not bad, (
        f"{rel_path}: {len(bad)} line(s) use a ticker outside the C-TEST-20 reserved set "
        f"(lines {bad}). Use ZZZT/QQQX/XQZW/ZQXY/QZZX with made-up quantities."
    )


def test_detector_flags_unreserved_tickers(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        'rows = ["individual,AAAA,1.5,2.25"]\n'
        'h = Holding(ticker="BBBB", qty=Decimal("1"))\n'
        'ok = ["individual,ZZZT,1,2", "QQQX"]\n',
        encoding="utf-8",
    )
    assert offending_lines(sample) == [1, 2]
