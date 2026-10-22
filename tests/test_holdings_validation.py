"""HoldingsLoader normalisation and rejection rules."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError

_HEADER = "account,symbol,shares,cost_basis_per_share"


def _csv(tmp_path: Path, *rows: str, header: str = _HEADER) -> Path:
    path = tmp_path / "holdings.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_ticker_is_stripped_and_uppercased(tmp_path: Path) -> None:
    snap = HoldingsLoader.load(_csv(tmp_path, "brokerage, zzzt ,12.3456,98.76"))
    assert snap.holdings[0].ticker == "ZZZT"


def test_spaces_after_commas_are_ignored(tmp_path: Path) -> None:
    snap = HoldingsLoader.load(_csv(tmp_path, "brokerage, QQQX, 40, 21.50"))
    assert snap.holdings[0].qty == Decimal("40")
    assert snap.holdings[0].cost_basis == Decimal("860.00")


def test_header_names_are_normalised(tmp_path: Path) -> None:
    path = _csv(
        tmp_path, "brokerage,XQZW,3.5,410", header=" Account ,SYMBOL, shares ,Cost_Basis_Per_Share"
    )
    assert HoldingsLoader.load(path).holdings[0].ticker == "XQZW"


@pytest.mark.parametrize("row", ["brokerage,,1,1", "brokerage,   ,1,1"])
def test_empty_symbol_is_rejected(tmp_path: Path, row: str) -> None:
    with pytest.raises(HoldingsLoadError, match="Empty symbol in CSV row 2"):
        HoldingsLoader.load(_csv(tmp_path, row))


@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "sNaN"])
@pytest.mark.parametrize("column", ["shares", "cost"])
def test_non_finite_numbers_are_rejected(tmp_path: Path, value: str, column: str) -> None:
    row = f"brokerage,ZZZT,{value},98.76" if column == "shares" else f"brokerage,ZZZT,1,{value}"
    with pytest.raises(HoldingsLoadError, match="Non-finite numeric value in CSV row 2"):
        HoldingsLoader.load(_csv(tmp_path, row))


@pytest.mark.parametrize("row", ["brokerage,ZZZT,-1,98.76", "brokerage,ZZZT,1,-0.01"])
def test_negative_numbers_are_rejected(tmp_path: Path, row: str) -> None:
    with pytest.raises(HoldingsLoadError, match="Negative numeric value in CSV row 2"):
        HoldingsLoader.load(_csv(tmp_path, row))


def test_zero_quantity_is_allowed(tmp_path: Path) -> None:
    assert HoldingsLoader.load(_csv(tmp_path, "brokerage,QZZX,0,55.10")).holdings[0].qty == 0


def test_error_messages_never_echo_row_values(tmp_path: Path) -> None:
    with pytest.raises(HoldingsLoadError) as exc:
        HoldingsLoader.load(_csv(tmp_path, "brokerage,ZQXY,NaN,12.34"))
    assert "ZQXY" not in str(exc.value)
    assert "12.34" not in str(exc.value)
