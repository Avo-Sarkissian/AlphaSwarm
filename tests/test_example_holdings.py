"""The shipped example holdings file loads and uses only the reserved fictional tickers."""

from __future__ import annotations

from alphaswarm.holdings.loader import HoldingsLoader
from alphaswarm.settings import PROJECT_ROOT

FICTIONAL_TICKERS = {"ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX"}


def test_example_holdings_load_with_fictional_tickers_only() -> None:
    snapshot = HoldingsLoader.load(PROJECT_ROOT / "examples" / "holdings.example.csv")
    assert len(snapshot.holdings) == 5
    assert {h.ticker for h in snapshot.holdings} == FICTIONAL_TICKERS
