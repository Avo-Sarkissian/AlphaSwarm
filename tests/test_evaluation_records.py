"""Eval records, JSONL helpers and run identity (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphaswarm.evaluation import (
    ABLATION_SUBSET_SIZE,
    SEED_BASE,
    BaselineRecord,
    EvalEvent,
    EvalPaths,
    OutcomeLabel,
    ablation_subset,
    append_jsonl,
    headcount_score,
    mean_bracket_temperature,
    normalize_rumor,
    read_jsonl,
    read_jsonl_if_exists,
    sim_seed_for,
    write_jsonl,
)
from alphaswarm.types import AgentDecision, BracketConfig, BracketType, SignalType
from tests.support.eval_data import make_event, make_events

EVENT_LINE = {
    "event_id": "evt-001",
    "timestamp": "2026-08-14T15:30:00+02:00",
    "rumor": "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.",
    "primary_ticker": "ZZZT",
    "benchmark": "SPY",
    "category": "m_and_a",
    "post_cutoff": True,
    "anonymized_rumor": "An industrial company is in late-stage talks to acquire a robotics maker.",
}


def test_event_parses_the_contract_format_and_normalizes_to_utc() -> None:
    event = EvalEvent.model_validate_json(json.dumps(EVENT_LINE))
    assert event.timestamp == datetime(2026, 8, 14, 13, 30, tzinfo=UTC)
    assert event.rumor_for("named").startswith("ZZZT Holdings")
    assert event.rumor_for("anon").startswith("An industrial company")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestamp", "2026-08-14T13:30:00"),
        ("primary_ticker", "zzzt"),
        ("event_id", "event-1"),
        ("category", "rumour"),
    ],
)
def test_event_rejects_bad_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        EvalEvent.model_validate({**EVENT_LINE, field: value})


def test_event_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        EvalEvent.model_validate({**EVENT_LINE, "outcome": "up"})


def test_label_reads_by_horizon() -> None:
    label = OutcomeLabel(
        event_id="evt-001",
        abn_ret_1d=0.012,
        abn_ret_5d=-0.004,
        vol_scale=0.018,
        label_1d="up",
        label_5d="flat",
    )
    assert (label.label("1d"), label.label("5d")) == ("up", "flat")
    assert (label.abn_ret("1d"), label.abn_ret("5d")) == (0.012, -0.004)


def test_read_jsonl_names_the_failing_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(EVENT_LINE) + "\n\n" + json.dumps({**EVENT_LINE, "post_cutoff": "maybe"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"events\.jsonl:3: post_cutoff"):
        read_jsonl(path, EvalEvent)


def test_write_append_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "results" / "baselines.jsonl"
    record = BaselineRecord(
        event_id="evt-002",
        variant="named",
        kind="single_k5",
        seed=1,
        k=5,
        n_valid=5,
        score=0.32,
        model="fake-worker",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert read_jsonl_if_exists(path, BaselineRecord) == []
    write_jsonl(path, [record])
    append_jsonl(path, record.model_copy(update={"seed": 2}))
    assert [r.seed for r in read_jsonl(path, BaselineRecord)] == [1, 2]
    assert not path.with_name("baselines.jsonl.tmp").exists()


def test_eval_paths_layout(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    assert paths.events == tmp_path / "events.jsonl"
    assert paths.fixture("evt-003", "named") == tmp_path / "fixtures" / "evt-003.json"
    assert paths.fixture("evt-003", "anon") == tmp_path / "fixtures" / "evt-003.anon.json"
    assert paths.headline_file("evt-003") == tmp_path / "headlines" / "evt-003.jsonl"
    assert paths.labels == tmp_path / "results" / "labels.jsonl"
    assert paths.probes == tmp_path / "results" / "probes.jsonl"
    assert paths.registered_simulation == tmp_path / "registered_simulation.json"


def test_normalize_rumor_collapses_whitespace() -> None:
    assert normalize_rumor("  ZZZT   Holdings\n is  ") == "ZZZT Holdings is"


def test_seed_and_subset_are_deterministic() -> None:
    assert [sim_seed_for(s) for s in (1, 2, 3)] == [SEED_BASE + 1, SEED_BASE + 2, SEED_BASE + 3]
    with pytest.raises(ValueError):
        sim_seed_for(0)
    ids = [e.event_id for e in make_events(16)]
    subset = ablation_subset(ids)
    assert len(subset) == ABLATION_SUBSET_SIZE
    assert subset == ablation_subset(list(reversed(ids)))
    assert set(subset) <= set(ids) and list(subset) == sorted(subset)
    assert ablation_subset(ids[:3]) == tuple(ids[:3])


def _bracket(bracket: BracketType, count: int, temperature: float) -> BracketConfig:
    # risk_profile is passed only while BracketConfig still has the field (it may be removed later).
    risk = {"risk_profile": 0.5} if "risk_profile" in BracketConfig.model_fields else {}
    return BracketConfig.model_validate(
        {
            "bracket_type": bracket,
            "display_name": bracket.value,
            "count": count,
            "temperature": temperature,
            "system_prompt_template": "fictional",
            "influence_weight_base": 0.5,
            **risk,
        }
    )


def test_mean_bracket_temperature_is_headcount_weighted() -> None:
    brackets = [_bracket(BracketType.QUANTS, 3, 0.2), _bracket(BracketType.DEGENS, 1, 1.0)]
    assert mean_bracket_temperature(brackets) == 0.4


def test_headcount_score_is_mean_signed_confidence_without_parse_errors() -> None:
    decisions = [
        AgentDecision(signal=SignalType.BUY, confidence=0.8),
        AgentDecision(signal=SignalType.SELL, confidence=0.4),
        AgentDecision(signal=SignalType.HOLD, confidence=0.9),
        AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0),
    ]
    score, n_valid = headcount_score(decisions)
    assert n_valid == 3
    assert score == pytest.approx((0.8 - 0.4) / 3)
    assert headcount_score([decisions[-1]]) == (0.0, 0)


def test_support_events_are_valid_and_dated_weekly() -> None:
    events = make_events(16)
    assert events[0].timestamp == datetime(2026, 2, 2, 14, 30, tzinfo=UTC)
    assert [e.post_cutoff for e in events[:5]] == [False, False, False, False, True]
    assert make_event(2).primary_ticker == "QQQX"
