"""PortfolioCache reloads the holdings CSV when its mtime changes.

See docs/DECISIONS.md#p39-d-07.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import alphaswarm.web.routes.holdings as holdings_module
from alphaswarm.web.routes.holdings import PortfolioCache

_HEADER = "account,symbol,shares,cost_basis_per_share"


def _write(path: Path, *rows: str, bump_ns: int = 0) -> None:
    path.write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")
    if bump_ns:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + bump_ns))


@pytest.fixture()
def load_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    real = holdings_module.load_portfolio_snapshot

    def _counting(path: Path) -> object:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(holdings_module, "load_portfolio_snapshot", _counting)
    return calls


async def test_missing_file_returns_none(tmp_path: Path) -> None:
    cache = PortfolioCache(tmp_path / "holdings.csv")
    assert await cache.get() is None
    assert cache.holdings_as_of is None


async def test_loads_once_until_mtime_changes(tmp_path: Path, load_calls: list[Path]) -> None:
    csv_path = tmp_path / "holdings.csv"
    _write(csv_path, "brokerage,ZZZT,12.3456,98.76")
    cache = PortfolioCache(csv_path)
    first = await cache.get()
    again = await cache.get()
    assert first is again
    assert len(load_calls) == 1
    _write(csv_path, "brokerage,QQQX,40,21.50", bump_ns=1_000_000_000)
    reloaded = await cache.get()
    assert reloaded is not None
    assert reloaded.holdings[0].ticker == "QQQX"
    assert len(load_calls) == 2
    assert cache.holdings_as_of == reloaded.as_of


async def test_malformed_file_is_none_then_recovers(tmp_path: Path) -> None:
    csv_path = tmp_path / "holdings.csv"
    # A non-numeric share count fails the loader however strict its row
    # validation is, so this test does not depend on those rules.
    _write(csv_path, "brokerage,ZZZT,not-a-number,98.76")
    cache = PortfolioCache(csv_path)
    assert await cache.get() is None
    _write(csv_path, "brokerage,ZZZT,1,98.76", bump_ns=1_000_000_000)
    snap = await cache.get()
    assert snap is not None
    assert snap.holdings[0].ticker == "ZZZT"


async def test_deleted_file_drops_the_snapshot(tmp_path: Path) -> None:
    csv_path = tmp_path / "holdings.csv"
    _write(csv_path, "brokerage,XQZW,3.5,410")
    cache = PortfolioCache(csv_path)
    assert await cache.get() is not None
    csv_path.unlink()
    assert await cache.get() is None
