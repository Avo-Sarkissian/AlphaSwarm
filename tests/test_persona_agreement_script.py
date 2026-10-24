"""scripts/persona_agreement.py: twin vs cross agreement per tag, no Neo4j."""

from __future__ import annotations

import pytest

from alphaswarm.personas import generate_personas, load_bracket_configs, prompt_twin_groups
from alphaswarm.types import AgentDecision, SignalType
from tests.support.scripts import load_script

PERSONAS = generate_personas(load_bracket_configs())
GROUPS = prompt_twin_groups(PERSONAS)
script = load_script("persona_agreement")


def _all(signal: SignalType) -> list[tuple[str, AgentDecision]]:
    return [(p.id, AgentDecision(signal=signal, confidence=0.6)) for p in PERSONAS]


def _alternating() -> list[tuple[str, AgentDecision]]:
    signals = (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
    return [(p.id, AgentDecision(signal=signals[i % 3], confidence=0.6)) for i, p in enumerate(PERSONAS)]


def _arms() -> list[object]:
    base = [
        script.cycle_stats(f"c{i}", "p76-baseline", f"seed-{i}", _all(SignalType.BUY), PERSONAS, GROUPS)
        for i in range(4)
    ]
    test = [script.cycle_stats(f"t{i}", "p76-traits", f"seed-{i}", _alternating(), PERSONAS, GROUPS) for i in range(4)]
    return [*base, *test]


def test_cycle_stats_and_paired_drop() -> None:
    stats = _arms()
    base = stats[0]
    assert base.twin == 1.0 and base.cross == 1.0 and base.within_entropy == 0.0 and base.bracket_tv == 0.0
    assert stats[4].twin is not None and stats[4].twin < 1.0
    drop = script.paired_drop(stats, "p76-baseline", "p76-traits")
    assert drop is not None
    mean_drop, dropped, seeds = drop
    assert mean_drop > 0 and (dropped, seeds) == (4, 4)
    assert script.paired_drop(stats, "p76-baseline", "missing-tag") is None


def test_summary_table_lists_each_tag() -> None:
    table = script.summary_table(_arms())
    lines = table.splitlines()
    assert lines[0].startswith("| tag | cycles | twin agreement")
    assert lines[2].startswith("| p76-baseline | 4 | 1.000 [1.000, 1.000]")
    assert lines[3].startswith("| p76-traits | 4 | ")
    single = script.summary_table([script.cycle_stats("c0", "solo", "s", _all(SignalType.HOLD), PERSONAS, GROUPS)])
    assert "| solo | 1 | 1.000 |" in single


def test_decisions_from_rows_skips_unknown_signals() -> None:
    rows = [
        {"agent_id": "quants_01", "signal": "buy", "confidence": 0.7},
        {"agent_id": "quants_02", "signal": "parse_error", "confidence": None},
        {"agent_id": "quants_03", "signal": "maybe", "confidence": 0.4},
    ]
    decisions = script.decisions_from_rows(rows)
    assert [(a, d.signal) for a, d in decisions] == [
        ("quants_01", SignalType.BUY),
        ("quants_02", SignalType.PARSE_ERROR),
    ]


def test_main_prints_the_table_and_the_paired_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fetched = [
        *[(f"c{i}", "p76-baseline", f"seed-{i}", _all(SignalType.BUY)) for i in range(4)],
        *[(f"t{i}", "p76-traits", f"seed-{i}", _alternating()) for i in range(4)],
    ]
    monkeypatch.setattr(script, "_fetch", lambda tags: fetched)
    assert script.main(["--tag", "p76-baseline", "--tag", "p76-traits"]) == 0
    out = capsys.readouterr().out
    assert "| p76-baseline | 4 |" in out
    assert "twin: mean(p76-baseline - p76-traits) = +" in out and "for 4/4 seeds" in out


def test_main_without_cycles_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(script, "_fetch", lambda tags: [])
    assert script.main(["--tag", "nothing"]) == 1
    assert "No complete cycles" in capsys.readouterr().out
