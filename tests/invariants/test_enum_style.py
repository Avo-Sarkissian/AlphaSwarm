"""Every enum is a StrEnum: str(), format() and f-strings render the value.

On Python 3.11 a `(str, Enum)` member renders as "SignalType.BUY" in an f-string;
a StrEnum renders "buy". Persisted and prompted text must never depend on that.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "alphaswarm"
ENUM_BASES = {"Enum", "enum.Enum", "IntEnum", "enum.IntEnum", "Flag", "enum.Flag", "StrEnum", "enum.StrEnum"}
STR_ENUM = {"StrEnum", "enum.StrEnum"}


def _enum_classes() -> list[tuple[str, str, set[str]]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if re.search(r" \d\.py$", path.name):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                bases = {ast.unparse(base) for base in node.bases}
                if bases & ENUM_BASES:
                    found.append((str(path.relative_to(SRC)), node.name, bases))
    return found


def test_every_enum_is_a_strenum() -> None:
    offenders = [
        f"{path}:{name} bases={sorted(bases)}"
        for path, name, bases in _enum_classes()
        if bases != {"StrEnum"} and bases != {"enum.StrEnum"}
    ]
    assert offenders == []
    assert {name for _, name, _ in _enum_classes()} >= {
        "BracketType",
        "SignalType",
        "FlipType",
        "EntityType",
        "SimulationPhase",
        "GovernorState",
        "PressureLevel",
        "ProviderRole",
        "ProviderType",
    }


def test_enum_members_render_their_value() -> None:
    from alphaswarm.governor import GovernorState
    from alphaswarm.memory_monitor import PressureLevel
    from alphaswarm.types import BracketType, EntityType, FlipType, SignalType, SimulationPhase

    assert f"{SignalType.BUY}" == "buy"
    assert str(BracketType.SELL_SIDE) == "sell_side"
    assert format(FlipType.BUY_TO_SELL) == "buy_to_sell"
    assert f"{EntityType.COMPANY:>8}" == " company"
    assert str(SimulationPhase.ROUND_2) == "round_2"
    assert str(GovernorState.PAUSED) == "paused"
    assert f"{PressureLevel.RED}" == "red"


def test_json_and_pydantic_values_unchanged() -> None:
    from alphaswarm.types import AgentDecision, SignalType

    decision = AgentDecision(signal=SignalType.HOLD, confidence=0.5)
    assert json.loads(decision.model_dump_json())["signal"] == "hold"
    assert decision.model_dump(mode="json")["signal"] == "hold"
    assert json.dumps([SignalType.BUY]) == '["buy"]'
    assert SignalType("sell") is SignalType.SELL
