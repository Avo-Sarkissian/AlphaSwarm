"""ISOL-01 unit tests: Holding and PortfolioSnapshot immutability and Decimal fields.

REVIEW HIGH additions: assert tuple-only collections (frozen dataclass does
not deep-freeze, so a list field would allow append/extend/pop).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alphaswarm.holdings.types import Holding, PortfolioSnapshot


def test_holding_constructs_with_decimal_qty_and_cost_basis() -> None:
    h = Holding(ticker="AAPL", qty=Decimal("10"), cost_basis=Decimal("150.25"))
    assert h.ticker == "AAPL"
    assert h.qty == Decimal("10")
    assert h.cost_basis == Decimal("150.25")


def test_holding_cost_basis_defaults_to_none() -> None:
    h = Holding(ticker="AAPL", qty=Decimal("10"))
    assert h.cost_basis is None


def test_holding_is_frozen() -> None:
    h = Holding(ticker="AAPL", qty=Decimal("10"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.qty = Decimal("20")  # type: ignore[misc]


def test_portfolio_snapshot_holdings_is_tuple() -> None:
    h1 = Holding(ticker="AAPL", qty=Decimal("10"))
    h2 = Holding(ticker="MSFT", qty=Decimal("5"))
    snap = PortfolioSnapshot(
        holdings=(h1, h2),
        as_of=datetime.now(UTC),
        account_number_hash="abcd1234",
    )
    assert isinstance(snap.holdings, tuple)
    assert len(snap.holdings) == 2


def test_portfolio_snapshot_holdings_is_not_a_list() -> None:
    """REVIEW HIGH: frozen dataclass doesn't block list mutation. Collection MUST be tuple."""
    snap = PortfolioSnapshot(
        holdings=(Holding(ticker="AAPL", qty=Decimal("1")),),
        as_of=datetime.now(UTC),
        account_number_hash="abcd1234",
    )
    assert not isinstance(snap.holdings, list)
    # Tuples have no .append / .extend / .pop — this is the mutation surface we close.
    assert not hasattr(snap.holdings, "append")
    assert not hasattr(snap.holdings, "extend")


def test_portfolio_snapshot_is_frozen() -> None:
    snap = PortfolioSnapshot(
        holdings=(),
        as_of=datetime.now(UTC),
        account_number_hash="abcd1234",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.account_number_hash = "xxxx"  # type: ignore[misc]


def test_holdings_types_import_only_stdlib() -> None:
    """Regression guard: holdings/types.py must not import pydantic, yfinance, structlog, httpx."""
    import pathlib

    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/holdings/types.py"
    content = src.read_text()
    forbidden = ("import pydantic", "import yfinance", "import structlog", "import httpx")
    for banned in forbidden:
        assert banned not in content, f"holdings/types.py must not contain '{banned}'"
