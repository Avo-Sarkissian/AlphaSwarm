"""Tests for scripts/privacy_scan.py, the owner-run count-only privacy scan.

Every value here is fictional (C-TEST-20 reserved tickers ZZZT, QQQX, XQZW and
made-up quantities). Rationale: docs/DECISIONS.md#adr-holdings-isolation.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "privacy_scan.py"

FICTIONAL_CSV = (
    "account,symbol,shares,cost_basis_per_share\n"
    "acct_a,ZZZT,12.3456,98.7654\n"
    "acct_b,QQQX,40,25.50\n"
    "acct_b,XQZW,7,310\n"
)
# Strings the scan must detect and must never print.
SECRET_STRINGS = (
    "12.3456",
    "98.7654",
    "1219.32",
    "1,219.32",
    "25.50",
    "1,020.00",
    "2,170.00",
    "ZZZT",
    "QQQX",
    "XQZW",
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("privacy_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["privacy_scan"] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ps() -> ModuleType:
    return _load_module()


@pytest.fixture()
def holdings_csv(tmp_path: Path) -> Path:
    path = tmp_path / "private" / "holdings.csv"
    path.parent.mkdir()
    path.write_text(FICTIONAL_CSV, encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(repo),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    result = subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    (root / "clean.md").write_text("nothing private here\n", encoding="utf-8")
    _git(root, "add", "clean.md")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _apply_rules(rules: list[str], text: str) -> str:
    """Apply filter-repo regex rules with Python re.sub, as git filter-repo does."""
    for rule in rules:
        pattern, _, replacement = rule.removeprefix("regex:").partition("==>")
        text = re.sub(pattern, replacement, text)
    return text


def _count_line(out: str, name: str) -> int | None:
    match = re.search(rf"^\s*(\d+)\s+.*{re.escape(name)}$", out, re.MULTILINE)
    return int(match.group(1)) if match else None


def test_load_positions_reads_fictional_csv(ps: ModuleType, holdings_csv: Path) -> None:
    positions = ps.load_positions(holdings_csv)
    assert [p.ticker for p in positions] == ["ZZZT", "QQQX", "XQZW"]
    assert {"12.3456", "98.7654", "1219.32", "1,219.32"} <= positions[0].values
    assert {"40", "25.50", "25.5", "1020.00", "1,020.00"} <= positions[1].values


def test_distinctive_value_matches_without_ticker(
    ps: ModuleType, holdings_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "notes.md"
    target.write_text(
        "intro\nposition size 12.3456 shares\nunrelated 12.34567\n", encoding="utf-8"
    )
    code = ps.main(["--csv", str(holdings_csv), "--repo", str(tmp_path), "--paths", str(target)])
    out = capsys.readouterr().out
    assert code == 1
    assert _count_line(out, "notes.md") == 1


def test_short_values_match_only_next_to_their_ticker(
    ps: ModuleType, holdings_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "table.md"
    target.write_text("QQQX,40,25.5\nwe ran 40 tests\nXQZW is 7 lots\n", encoding="utf-8")
    code = ps.main(["--csv", str(holdings_csv), "--repo", str(tmp_path), "--paths", str(target)])
    assert code == 1
    assert _count_line(capsys.readouterr().out, "table.md") == 1


def test_decimal_continuation_is_not_a_match(
    ps: ModuleType, holdings_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "prices.md"
    target.write_text("QQQX traded 40.5 today\n", encoding="utf-8")
    code = ps.main(["--csv", str(holdings_csv), "--repo", str(tmp_path), "--paths", str(target)])
    assert code == 0
    assert "0 matching line(s) in 0 file(s)" in capsys.readouterr().out


def test_range_mode_counts_blobs_deleted_later_in_range(
    ps: ModuleType, holdings_csv: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "leak.md").write_text("ZZZT 12.3456\n", encoding="utf-8")
    _git(repo, "add", "leak.md")
    _git(repo, "commit", "-q", "-m", "add")
    _git(repo, "rm", "-q", "leak.md")
    _git(repo, "commit", "-q", "-m", "remove")
    assert _git(repo, "diff", base, "HEAD") == ""  # the net diff hides the leak
    code = ps.main(
        ["--csv", str(holdings_csv), "--repo", str(repo), "--range", f"{base}..HEAD"]
    )
    assert code == 1
    assert _count_line(capsys.readouterr().out, "leak.md") == 1


def test_all_history_and_tree_modes(
    ps: ModuleType, holdings_csv: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "switch", "-q", "-c", "side")
    (repo / "side.md").write_text("cost 1,020.00\n", encoding="utf-8")
    _git(repo, "add", "side.md")
    _git(repo, "commit", "-q", "-m", "side")
    _git(repo, "switch", "-q", "master")
    (repo / "untracked.md").write_text("ZZZT 12.3456\n", encoding="utf-8")
    assert ps.main(["--csv", str(holdings_csv), "--repo", str(repo), "--tree"]) == 0
    capsys.readouterr()
    assert ps.main(["--csv", str(holdings_csv), "--repo", str(repo), "--all-history"]) == 1
    assert _count_line(capsys.readouterr().out, "side.md") == 1


def test_output_and_errors_never_echo_values(
    ps: ModuleType, holdings_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "everything.md"
    target.write_text(
        "ZZZT 12.3456 98.7654 1219.32\nQQQX,40,25.50 1,020.00\nXQZW 310 2,170.00\n",
        encoding="utf-8",
    )
    assert ps.main(
        ["--csv", str(holdings_csv), "--repo", str(tmp_path), "--paths", str(target)]
    ) == 1
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "account,symbol,shares,cost_basis_per_share\nacct_a,ZZZT,12.3456,not-a-number\n",
        encoding="utf-8",
    )
    assert ps.main(["--csv", str(bad), "--repo", str(tmp_path), "--paths", str(target)]) == 2
    captured = capsys.readouterr()
    assert "row 2: column cost_basis_per_share is not a finite number" in captured.err
    for secret in (*SECRET_STRINGS, "not-a-number"):
        assert secret not in captured.out + captured.err


def test_missing_columns_is_an_input_error(
    ps: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("account,symbol,shares\nacct_a,ZZZT,1\n", encoding="utf-8")
    target = tmp_path / "x.md"
    target.write_text("x\n", encoding="utf-8")
    assert ps.main(["--csv", str(bad), "--repo", str(tmp_path), "--paths", str(target)]) == 2
    assert "missing columns: ['cost_basis_per_share']" in capsys.readouterr().err


def test_emit_refuses_a_path_inside_the_repository(
    ps: ModuleType, holdings_csv: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = repo / "rules.txt"
    code = ps.main(
        ["--csv", str(holdings_csv), "--repo", str(repo), "--emit-replace-text", str(target)]
    )
    assert code == 2
    assert not target.exists()
    assert "inside the repository" in capsys.readouterr().err


def test_emitted_rules_are_owner_only_and_redact_every_match(
    ps: ModuleType, holdings_csv: Path, repo: Path, tmp_path: Path
) -> None:
    out_file = tmp_path / "archive" / "replacements.txt"
    code = ps.main(
        ["--csv", str(holdings_csv), "--repo", str(repo), "--emit-replace-text", str(out_file)]
    )
    assert code == 0
    assert stat.S_IMODE(out_file.stat().st_mode) == 0o600
    rules = out_file.read_text(encoding="utf-8").splitlines()
    assert rules
    assert all(rule.startswith("regex:") and "==>" in rule for rule in rules)
    sample = (
        "QQQX,40,25.50\n"
        "ZZZT holds 12.3456 at 98.7654\n"
        "cost 1,020.00 for QQQX\n"
        "40 units of QQQX\n"
        "keep 40 tests\n"
    )
    redacted = _apply_rules(rules, sample)
    needles = ps.build_needles(ps.load_positions(holdings_csv))
    assert ps.count_matching_lines(sample, needles) == 4
    assert ps.count_matching_lines(redacted, needles) == 0
    assert "keep 40 tests" in redacted


def test_show_lines_prints_line_numbers_not_content(
    ps: ModuleType, holdings_csv: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "doc.md"
    target.write_text("a\nZZZT 12.3456\nb\nQQQX,40\n", encoding="utf-8")
    args = ["--csv", str(holdings_csv), "--repo", str(tmp_path), "--paths", str(target)]
    code = ps.main([*args, "--show-lines"])
    out = capsys.readouterr().out
    assert code == 1
    assert f"{target}:2,4" in out
    for secret in SECRET_STRINGS:
        assert secret not in out
