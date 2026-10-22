"""Unit tests for tests/support/golden.py (offline)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import pytest
from neo4j.time import DateTime as Neo4jDateTime

from alphaswarm.types import SignalType
from tests.support.golden import GOLDEN_ROOT, assert_golden, assert_golden_file, normalize

CYCLE = "1b4e28ba-2fa1-41d2-883f-0016d3cca427"
OTHER = "6f9619ff-8b86-4011-b42d-00cf4fc964ff"


@dataclasses.dataclass(frozen=True)
class _Row:
    agent_id: str
    signal: SignalType


@pytest.fixture(autouse=True)
def _no_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPDATE_GOLDEN", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_uuids_are_numbered_by_first_appearance() -> None:
    data = {"a": CYCLE, "b": [OTHER, CYCLE], "c": f"cycle {OTHER} done"}
    assert normalize(data) == {
        "a": "<UUID:1>",
        "b": ["<UUID:2>", "<UUID:1>"],
        "c": "cycle <UUID:2> done",
    }


def test_timestamps_floats_enums_and_dataclasses_are_stable() -> None:
    data = {
        "py": dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC),
        "neo": Neo4jDateTime(2026, 10, 3, 12, 0, 0),
        "iso": "generated 2026-10-03T12:00:00.123+00:00",
        "f": 0.1234564999,
        "neg_zero": -0.0000001,
        "row": _Row(agent_id="quants_01", signal=SignalType.BUY),
    }
    assert normalize(data) == {
        "py": "<TS>",
        "neo": "<TS>",
        "iso": "generated <TS>",
        "f": 0.123456,
        "neg_zero": 0.0,
        "row": {"agent_id": "quants_01", "signal": "buy"},
    }


def test_unsupported_type_raises() -> None:
    with pytest.raises(TypeError, match="unsupported type"):
        normalize({"x": object()})


def test_match_passes_and_mismatch_shows_unified_diff(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    path.write_text('{\n  "a": 1\n}\n', encoding="utf-8")
    assert_golden_file(path, {"a": 1})
    with pytest.raises(AssertionError) as excinfo:
        assert_golden_file(path, {"a": 2})
    message = str(excinfo.value)
    assert '-  "a": 1' in message
    assert '+  "a": 2' in message


def test_missing_golden_fails_with_instructions(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="UPDATE_GOLDEN=1"):
        assert_golden_file(tmp_path / "missing.md", "text")


def test_update_mode_writes_text_with_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    path = tmp_path / "sub" / "g.md"
    assert_golden_file(path, f"cycle {CYCLE}")
    assert path.read_text(encoding="utf-8") == "cycle <UUID:1>\n"


def test_update_mode_is_refused_in_ci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPDATE_GOLDEN", "1")
    monkeypatch.setenv("CI", "true")
    with pytest.raises(AssertionError, match="not allowed in CI"):
        assert_golden_file(tmp_path / "g.md", "text")
    assert not (tmp_path / "g.md").exists()


def test_relative_path_cannot_escape_golden_root() -> None:
    with pytest.raises(ValueError, match="must stay under"):
        assert_golden("../outside.json", {"a": 1})
    assert GOLDEN_ROOT.name == "golden"
