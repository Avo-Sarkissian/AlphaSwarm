"""Tests for scripts/ticker_scan.py, the count-only owner-ticker scan.

Fictional tickers only (docs/DECISIONS.md#adr-holdings-isolation). The real ticker
set lives in the gitignored data/sector_map.local.json and is never read here.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ticker_scan.py"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ticker_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ticker_scan"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sector_map(tmp_path: Path) -> Path:
    entry = {
        "sector": "Robotics",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.9,
    }
    path = tmp_path / "sector_map.local.json"
    path.write_text(json.dumps({"tickers": {"ZZZT": entry, "qqqx": entry}}), encoding="utf-8")
    return path


def test_pattern_matches_standalone_tokens_only(ts: ModuleType) -> None:
    pattern = ts.build_pattern({"ZZZT", "QQQX"})
    text = "ZZZT rallied; $QQQX too. ZZZTX, zzzt, ZZZT_1 and AZZZT do not count."
    assert ts.count_matches(text, pattern) == 2


def test_json_and_python_sources(ts: ModuleType) -> None:
    assert ts.tickers_from_sector_map_json('{"tickers": {" zzzt ": {}, "QQQX": {}}}') == frozenset({"ZZZT", "QQQX"})
    source = 'SECTOR_MAP: dict[str, dict[str, str]] = {"ZZZT": {}, "xqzw": {}}\nOTHER = {"QZZX": 1}\n'
    assert ts.tickers_from_python_source(source) == frozenset({"ZZZT", "XQZW"})
    with pytest.raises(ValueError):
        ts.tickers_from_sector_map_json('{"tickers": {}}')
    with pytest.raises(ValueError):
        ts.tickers_from_python_source("X = 1\n")


def test_cli_prints_counts_and_lines_never_tickers(
    ts: ModuleType,
    sector_map: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tree = tmp_path / "tree"
    (tree / "node_modules").mkdir(parents=True)
    (tree / "a.py").write_text("x = 'ZZZT'\ny = 1\nz = 'QQQX ZZZT'\n", encoding="utf-8")
    (tree / "b.md").write_text("nothing here\n", encoding="utf-8")
    (tree / "node_modules" / "c.js").write_text("ZZZT\n", encoding="utf-8")
    (tree / "a 2.py").write_text("ZZZT\n", encoding="utf-8")
    code = ts.main(["--sector-map", str(sector_map), "--show-lines", str(tree)])
    out = capsys.readouterr().out
    assert code == 1
    assert f"{tree / 'a.py'}: 3 lines [1, 3]" in out
    assert out.strip().endswith("total: 3")
    stripped = out.replace(str(tmp_path), "")
    assert "ZZZT" not in stripped
    assert "QQQX" not in stripped


def test_clean_input_exits_zero(
    ts: ModuleType,
    sector_map: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean = tmp_path / "clean.txt"
    clean.write_text("no holdings here\n", encoding="utf-8")
    assert ts.main(["--sector-map", str(sector_map), str(clean)]) == 0
    assert capsys.readouterr().out.strip() == "total: 0"


def test_stdin_mode(
    ts: ModuleType,
    sector_map: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("diff --git\n+ZZZT\n-QQQX\n"))
    assert ts.main(["--sector-map", str(sector_map), "--stdin"]) == 1
    assert capsys.readouterr().out.strip() == "<stdin>: 2"


def test_missing_sector_map_is_an_input_error(
    ts: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ts.main(["--sector-map", str(tmp_path / "missing.json"), str(tmp_path)]) == 2
    assert "FileNotFoundError" in capsys.readouterr().err


def test_missing_scan_path_is_an_input_error(
    ts: ModuleType, sector_map: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped PATH must not pass as a clean scan."""
    assert ts.main(["--sector-map", str(sector_map), str(tmp_path / "absent")]) == 2
    captured = capsys.readouterr()
    assert "no such path" in captured.err
    assert "total:" not in captured.out
