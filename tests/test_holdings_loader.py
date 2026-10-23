"""HOLD-01 + HOLD-02 unit tests for HoldingsLoader.

Hermetic: every test writes its own CSV fixture under tmp_path. No dependency
on Schwab/holdings.csv — these tests pass in any environment including CI
containers that do not ship the real data file.

Fixture data is fictional (C-TEST-20): only the reserved tickers ZZZT, QQQX,
XQZW, ZQXY and QZZX with made-up quantities and cost basis. Never paste real
positions here; tests/invariants/test_fictional_fixtures.py enforces the
ticker half of that rule (docs/DECISIONS.md#adr-holdings-isolation).

pytest-asyncio asyncio_mode='auto' is configured project-wide, but this module
contains no async tests (the loader is sync-only inside lifespan). pytest-socket
--disable-socket is global — these tests touch no network.

Review-mandated tests (2026-04-19 cross-AI review):
- test_same_ticker_multiple_accounts (Gemini + Codex LOW): documents the
  per-row / no-summing contract for a ticker that appears in multiple accounts.
- test_load_bom_prefixed_csv (Codex LOW): verifies encoding="utf-8-sig" handles
  BOM-prefixed Schwab exports correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import alphaswarm.holdings.loader as loader_module
from alphaswarm.holdings import HoldingsLoader, HoldingsLoadError, PortfolioSnapshot
from alphaswarm.security.hashing import sha256_first8
from tests.support.log_capture import RenderedLog

# --------- Fixture helpers (hermetic tmp_path CSVs) ---------


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    """Write a CSV at `path` with the given header + body rows. Returns path."""
    body = "\n".join([header, *rows]) + ("\n" if rows else "")
    path.write_text(body, encoding="utf-8")
    return path


_DEFAULT_HEADER = "account,symbol,shares,cost_basis_per_share"


def _schwab_like_csv(tmp_path: Path, rows: list[str]) -> Path:
    """Write a Schwab-shaped CSV to tmp_path/holdings.csv and return the path."""
    return _write_csv(tmp_path / "holdings.csv", _DEFAULT_HEADER, rows)


# --------- Happy path ---------


def test_load_returns_portfolio_snapshot(tmp_path: Path) -> None:
    """HOLD-01 — load() returns a PortfolioSnapshot with the expected shape."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,12.3456,45.67",
            "roth_ira,QQQX,3.5,210.25",
        ],
    )
    snap = HoldingsLoader.load(path)
    assert isinstance(snap, PortfolioSnapshot)
    assert len(snap.holdings) == 2
    assert isinstance(snap.holdings, tuple)
    assert isinstance(snap.account_number_hash, str)
    assert len(snap.account_number_hash) == 8
    # account_number_hash is 8 hex chars
    assert all(c in "0123456789abcdef" for c in snap.account_number_hash)
    assert isinstance(snap.as_of, datetime)
    assert snap.as_of.tzinfo is UTC


def test_cost_basis_is_total(tmp_path: Path) -> None:
    """D-02 — cost_basis = Decimal(shares) * Decimal(cost_basis_per_share). Total, not per-share."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,12.5,80"])
    snap = HoldingsLoader.load(path)
    h = snap.holdings[0]
    assert h.ticker == "ZZZT"
    assert h.qty == Decimal("12.5")
    # Total cost, not per-share.
    assert h.cost_basis == Decimal("12.5") * Decimal("80")
    assert h.cost_basis == Decimal("1000.0")
    # Negative assertions: it is NOT the per-share value, and it is NOT the bare shares value.
    assert h.cost_basis != Decimal("80")
    assert h.cost_basis != Decimal("12.5")


def test_fractional_shares_preserve_decimal_precision(tmp_path: Path) -> None:
    """Research Pitfall 1 — Decimal(string), never Decimal(float)."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,12.3456,1234.56"])
    snap = HoldingsLoader.load(path)
    assert snap.holdings[0].qty == Decimal("12.3456")
    # If the loader had used float(row["shares"]) first, this string equality would fail.
    assert str(snap.holdings[0].qty) == "12.3456"


def test_row_order_preserved(tmp_path: Path) -> None:
    """Holdings tuple order matches CSV row order."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,2,3",
            "individual,QQQX,2,3",
            "roth_ira,XQZW,2,3",
            "roth_ira,ZQXY,2,3",
        ],
    )
    snap = HoldingsLoader.load(path)
    assert [h.ticker for h in snap.holdings] == ["ZZZT", "QQQX", "XQZW", "ZQXY"]


def test_holdings_tuple_is_immutable(tmp_path: Path) -> None:
    """PortfolioSnapshot.holdings MUST be a tuple — the loader converts list -> tuple."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,2,3"])
    snap = HoldingsLoader.load(path)
    assert isinstance(snap.holdings, tuple)
    assert not hasattr(snap.holdings, "append")


def test_as_of_is_tz_aware_utc(tmp_path: Path) -> None:
    """Pitfall 6 — datetime.fromtimestamp(mtime, tz=UTC) produces tz-aware UTC."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,2,3"])
    snap = HoldingsLoader.load(path)
    assert snap.as_of.tzinfo is UTC


# --------- D-04 (all positions) + D-03 (multi-account merge) ---------


def test_all_rows_included(tmp_path: Path) -> None:
    """D-04 — a money-market row (QZZX here) passes through, no filtering."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,20,30",
            "individual,QZZX,5000,1",  # money-market style row — D-04 says include
            "roth_ira,QQQX,4.0283,321.1234",
        ],
    )
    snap = HoldingsLoader.load(path)
    tickers = [h.ticker for h in snap.holdings]
    assert "QZZX" in tickers
    assert len(snap.holdings) == 3


def test_multi_account_merged_into_single_snapshot(tmp_path: Path) -> None:
    """D-03 — individual + roth_ira rows collapse into ONE PortfolioSnapshot."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,20,30",
            "individual,QQQX,15,40",
            "roth_ira,XQZW,8,55",
        ],
    )
    snap = HoldingsLoader.load(path)
    assert isinstance(snap, PortfolioSnapshot)
    assert len(snap.holdings) == 3
    # All three are in the SAME snapshot — the return type is PortfolioSnapshot,
    # not list[PortfolioSnapshot] or dict[str, PortfolioSnapshot].


def test_same_ticker_multiple_accounts(tmp_path: Path) -> None:
    """Cross-AI review LOW (Gemini + Codex) — same-ticker-multi-account contract.

    D-03 says "multi-account rows collapse into one snapshot" but does NOT
    specify what happens when ZZZT appears in BOTH `individual` and `roth_ira`.
    This test locks the contract: TWO separate Holding entries — no summing,
    no weighted averaging, no per-ticker dedup. Rows are appended 1:1 from
    the CSV. Rationale: IRA vs taxable are tax-distinct lots; per-row
    granularity preserves audit traceability for Phase 41 advisory synthesis.
    """
    path = _schwab_like_csv(
        tmp_path,
        [
            # ZZZT in BOTH accounts with different share counts + costs
            "individual,ZZZT,30,45",  # 30 shares @ $45 = $1,350 cost basis
            "roth_ira,ZZZT,12,60",  # 12 shares @ $60 = $720 cost basis
        ],
    )
    snap = HoldingsLoader.load(path)

    # Contract: two separate Holding entries, not one summed entry
    assert len(snap.holdings) == 2, (
        "Same ticker in two accounts MUST produce two Holding entries — summing would conflate tax-distinct lots"
    )

    # Both entries are ZZZT
    tickers = [h.ticker for h in snap.holdings]
    assert tickers == ["ZZZT", "ZZZT"]

    # The per-account quantities are DIFFERENT — proves no summing (30+12=42)
    qtys = sorted([h.qty for h in snap.holdings])
    assert qtys == [Decimal("12"), Decimal("30")]
    assert Decimal("42") not in qtys  # would be the summed value

    # Cost basis per entry matches its own row's qty * cost_per_share
    # (no weighted average was computed)
    cost_bases = sorted([h.cost_basis for h in snap.holdings if h.cost_basis is not None])
    assert cost_bases == [
        Decimal("12") * Decimal("60"),  # $720 — roth_ira row
        Decimal("30") * Decimal("45"),  # $1,350 — individual row
    ]

    # Account hash still reflects BOTH accounts (sorted, joined with '|')
    assert snap.account_number_hash == sha256_first8("individual|roth_ira")


# --------- HOLD-02 account hash ---------


def test_account_hash(tmp_path: Path) -> None:
    """HOLD-02 — account_number_hash = sha256_first8('|'.join(sorted(account_labels)))."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,20,30",
            "roth_ira,QQQX,15,40",
        ],
    )
    snap = HoldingsLoader.load(path)
    expected = sha256_first8("individual|roth_ira")
    assert snap.account_number_hash == expected


def test_account_hash_is_sort_order_stable(tmp_path: Path) -> None:
    """Hash is stable regardless of CSV row order — uses sorted(account_labels)."""
    path = _schwab_like_csv(
        tmp_path,
        [
            # roth_ira FIRST — the loader must still sort before joining.
            "roth_ira,QQQX,15,40",
            "roth_ira,XQZW,8,55",
            "individual,ZZZT,20,30",
        ],
    )
    snap = HoldingsLoader.load(path)
    assert snap.account_number_hash == sha256_first8("individual|roth_ira")


def test_account_label_not_in_hash_output(tmp_path: Path) -> None:
    """HOLD-02 — the raw account labels do not appear in the hash string."""
    path = _schwab_like_csv(
        tmp_path,
        [
            "individual,ZZZT,20,30",
            "roth_ira,QQQX,15,40",
        ],
    )
    snap = HoldingsLoader.load(path)
    assert "individual" not in snap.account_number_hash
    assert "roth_ira" not in snap.account_number_hash


def test_single_account_hash(tmp_path: Path) -> None:
    """Single-account CSV — hash is sha256_first8('individual') (sorted of one-element set)."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,20,30"])
    snap = HoldingsLoader.load(path)
    assert snap.account_number_hash == sha256_first8("individual")


def test_account_labels_never_reach_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label is free text and may be an account number, so the log gets a count only."""
    rendered = RenderedLog()
    monkeypatch.setattr(loader_module, "log", rendered)
    HoldingsLoader.load(_schwab_like_csv(tmp_path, ["acct-0000-9999,ZZZT,20,30"]))
    assert rendered.events == ["holdings_loaded"]
    assert '"account_count": 1' in rendered.text
    assert "acct-0000-9999" not in rendered.text


# --------- Error paths (D-08) ---------


def test_load_missing_file(tmp_path: Path) -> None:
    """Missing file → HoldingsLoadError('CSV not found: ...')."""
    with pytest.raises(HoldingsLoadError) as excinfo:
        HoldingsLoader.load(tmp_path / "nonexistent.csv")
    assert "not found" in str(excinfo.value).lower()


def test_load_malformed_csv_missing_column(tmp_path: Path) -> None:
    """Missing required column → HoldingsLoadError('CSV missing columns: ...')."""
    path = _write_csv(
        tmp_path / "holdings.csv",
        "account,symbol,shares",  # missing cost_basis_per_share
        ["individual,ZZZT,2"],
    )
    with pytest.raises(HoldingsLoadError) as excinfo:
        HoldingsLoader.load(path)
    assert "missing columns" in str(excinfo.value).lower()
    assert "cost_basis_per_share" in str(excinfo.value)


def test_load_malformed_csv_invalid_numeric(tmp_path: Path) -> None:
    """Non-numeric cell → HoldingsLoadError chained from InvalidOperation."""
    path = _schwab_like_csv(tmp_path, ["individual,ZZZT,notanumber,30"])
    with pytest.raises(HoldingsLoadError) as excinfo:
        HoldingsLoader.load(path)
    assert "invalid numeric" in str(excinfo.value).lower()
    # chained — __cause__ must reference the underlying InvalidOperation
    assert excinfo.value.__cause__ is not None


def test_load_empty_csv_no_header(tmp_path: Path) -> None:
    """Zero-byte file → HoldingsLoadError('CSV is empty — no header row')."""
    path = tmp_path / "holdings.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(HoldingsLoadError) as excinfo:
        HoldingsLoader.load(path)
    msg = str(excinfo.value).lower()
    assert "empty" in msg or "no header" in msg


def test_load_empty_body_header_only(tmp_path: Path) -> None:
    """Header-only file → HoldingsLoadError('CSV has no data rows') BEFORE sha256_first8.

    Research Pitfall 2: sha256_first8('') raises TypeError, so the empty-body
    guard MUST run first. If this test catches TypeError instead of
    HoldingsLoadError, the guard is missing or misordered.
    """
    path = _schwab_like_csv(tmp_path, [])  # header only, no data rows
    with pytest.raises(HoldingsLoadError) as excinfo:
        HoldingsLoader.load(path)
    assert "no data rows" in str(excinfo.value).lower()


def test_load_bom_prefixed_csv(tmp_path: Path) -> None:
    """Cross-AI review LOW (Codex) — encoding='utf-8-sig' handles UTF-8 BOM.

    Schwab web exports can be UTF-8 BOM-prefixed (\\xef\\xbb\\xbf at byte 0).
    With plain encoding='utf-8' the BOM lands in the first header name as
    '\\ufeffaccount' and REQUIRED_COLUMNS fails with 'missing columns: account'.
    With encoding='utf-8-sig' (Python stdlib) the BOM is transparently stripped
    on read and the header parses cleanly.

    This test writes BOM bytes directly to the file (bypassing Python's
    utf-8 encoder, which does NOT emit a BOM for 'utf-8') and confirms the
    loader returns a valid PortfolioSnapshot instead of raising.
    """
    path = tmp_path / "holdings.csv"
    # Write BOM (3 bytes: 0xEF 0xBB 0xBF) followed by the CSV body as UTF-8
    csv_body = "account,symbol,shares,cost_basis_per_share\nindividual,ZZZT,2,3\nroth_ira,QQQX,5,7\n"
    path.write_bytes(b"\xef\xbb\xbf" + csv_body.encode("utf-8"))

    # Without encoding='utf-8-sig' this would raise HoldingsLoadError
    # ('missing columns: [account]') because reader.fieldnames[0] would be
    # '﻿account'. With utf-8-sig it parses cleanly.
    snap = HoldingsLoader.load(path)
    assert isinstance(snap, PortfolioSnapshot)
    assert len(snap.holdings) == 2
    assert snap.holdings[0].ticker == "ZZZT"
    assert snap.holdings[0].qty == Decimal("2")
    assert snap.holdings[1].ticker == "QQQX"
    # Account hash still works because the account column was parsed correctly
    assert snap.account_number_hash == sha256_first8("individual|roth_ira")


# --------- Meta: source-file invariants (grep-level guards) ---------


def test_loader_module_uses_decimal_string_never_decimal_float() -> None:
    """Research Pitfall 1 — source MUST use Decimal(row[...]) and MUST NOT use float(row[...])."""
    src = Path(__file__).parent.parent / "src/alphaswarm/holdings/loader.py"
    content = src.read_text(encoding="utf-8")
    assert "Decimal(row[" in content
    assert "float(row[" not in content


def test_loader_module_uses_utf8_sig_encoding() -> None:
    """Codex review LOW — source MUST use encoding='utf-8-sig' for BOM safety."""
    src = Path(__file__).parent.parent / "src/alphaswarm/holdings/loader.py"
    content = src.read_text(encoding="utf-8")
    assert 'encoding="utf-8-sig"' in content, (
        "loader.py must open CSV with encoding='utf-8-sig' to handle BOM-prefixed Schwab exports"
    )
    # Negative assertion: the plain encoding='utf-8' must NOT appear on the
    # open() call. (Other occurrences of "utf-8" in docstrings/comments are OK
    # because they're not in a keyword-arg position; this check is stricter.)
    assert 'path.open(newline="", encoding="utf-8")' not in content, (
        "loader.py must NOT use plain encoding='utf-8' on path.open — use 'utf-8-sig' for BOM safety"
    )


def test_loader_module_does_not_log_holding_field_values() -> None:
    """Research Pitfall 7 / ISOL-07 boundary — loader must not log ticker/qty/cost_basis."""
    import re as _re

    src = Path(__file__).parent.parent / "src/alphaswarm/holdings/loader.py"
    content = src.read_text(encoding="utf-8")
    # Tolerate substrings like 'cost_basis_per_share' in REQUIRED_COLUMNS; the
    # sensitive pattern is the Holding attribute names inside a structlog emit.
    for forbidden in ("log.info.*qty=", "log.info.*cost_basis=", "log.info.*ticker="):
        assert not _re.search(forbidden, content), (
            f"loader.py must not log Holding field values — found pattern {forbidden!r}"
        )
