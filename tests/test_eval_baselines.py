"""Worker baselines and the memorization probe (docs/methodology.md §5, §8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphaswarm.errors import AuthError
from alphaswarm.evaluation import (
    BaselineRecord,
    EvalPaths,
    ProbeRecord,
    read_jsonl,
    sim_seed_for,
)
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.manifest import derive_call_seed
from alphaswarm.types import SignalType
from tests.inference.fakes import FakeInferenceProvider
from tests.support.controllers import ImmediateController
from tests.support.eval_data import make_event, make_events
from tests.support.eval_scripts import load_eval_script

baselines = load_eval_script("baselines")
CONFIG = baselines.default_worker_config()


def _decision(signal: str, confidence: float) -> InferenceResult:
    payload = {
        "rationale": "fictional",
        "signal": signal,
        "confidence": confidence,
        "sentiment": 0.0,
        "cited_agents": [],
    }
    return InferenceResult(content=json.dumps(payload), model="fake-worker")


def test_baseline_config_is_a_neutral_analyst_at_the_mean_temperature() -> None:
    assert CONFIG["agent_id"] == baselines.BASELINE_AGENT_ID
    assert CONFIG["temperature"] == baselines.BASELINE_TEMPERATURE == 0.57
    assert CONFIG["system_prompt"].startswith(baselines.BASELINE_ANALYST_PROMPT)
    assert "Sell-Side" not in CONFIG["system_prompt"]


def test_call_seeds_are_derived_per_kind_seed_and_sample() -> None:
    seeds = baselines.call_seeds("single_k5", 2, 3)
    assert seeds == [derive_call_seed(sim_seed_for(2), "baseline_single_k5", i) for i in (1, 2, 3)]
    assert len(set(seeds)) == 3
    assert seeds != baselines.call_seeds("self_consistency", 2, 3)


async def test_sample_decisions_sends_the_fixture_block_and_seeds() -> None:
    replies = {1: ("buy", 0.8), 2: ("sell", 0.4), 3: ("hold", 0.9)}
    seeds = baselines.call_seeds("single_k5", 1, 3)

    def reply(**kwargs: Any) -> InferenceResult:
        signal, confidence = replies[seeds.index(kwargs["seed"]) + 1]
        return _decision(signal, confidence)

    provider = FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=reply)
    controller = ImmediateController()
    decisions = await baselines.sample_decisions(
        provider,
        controller,
        CONFIG,
        rumor="ZZZT Holdings explores a sale (fictional).",
        market_context="== ZZZT ==\nPrice: $123.45",
        seeds=seeds,
    )
    assert [d.signal for d in decisions] == [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert controller.acquired == controller.released == 3
    first = provider.calls[0]
    assert first["temperature"] == 0.57
    assert any("Price: $123.45" in str(m["content"]) for m in first["messages"])


async def test_a_failed_call_becomes_parse_error_but_auth_errors_propagate() -> None:
    def flaky(**kwargs: Any) -> InferenceResult:
        if kwargs["seed"] % 2:
            raise RuntimeError("connection reset")
        return _decision("buy", 0.6)

    seeds = [10, 11, 12]
    provider = FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=flaky)
    decisions = await baselines.sample_decisions(
        provider,
        ImmediateController(),
        CONFIG,
        rumor="fictional rumor text",
        market_context=None,
        seeds=seeds,
    )
    assert [d.signal for d in decisions] == [SignalType.BUY, SignalType.PARSE_ERROR, SignalType.BUY]

    def denied(**kwargs: Any) -> InferenceResult:
        raise AuthError("key rejected", provider="fake", model="fake-worker")

    with pytest.raises(AuthError):
        await baselines.sample_decisions(
            FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=denied),
            ImmediateController(),
            CONFIG,
            rumor="fictional rumor text",
            market_context=None,
            seeds=seeds,
        )


async def test_probe_records_recall_and_parse_failures() -> None:
    event = make_event(1)
    answer = {"recalled": True, "direction": "up", "rationale": "fictional memory"}
    good = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake-worker",
        scripted=[InferenceResult(content=json.dumps(answer), model="fake-worker")],
    )
    record = await baselines.probe_event(good, ImmediateController(), CONFIG, event)
    assert (record.recalled, record.direction, record.parse_failed) == (True, "up", False)
    user = " ".join(str(m["content"]) for m in good.calls[0]["messages"])
    assert "2026-02-02" in user and "ZZZT" in user
    garbage = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake-worker",
        scripted=[InferenceResult(content="no idea", model="fake-worker")] * 4,
    )
    failed = await baselines.probe_event(garbage, ImmediateController(), CONFIG, event)
    assert (failed.recalled, failed.direction, failed.parse_failed) == (False, "unknown", True)


def test_units_and_resume() -> None:
    events = make_events(2)
    single = baselines.baseline_units("single_k5", events)
    assert [(u.event.event_id, u.variant, u.seed) for u in single] == [
        ("evt-001", "named", 1),
        ("evt-001", "named", 2),
        ("evt-001", "named", 3),
        ("evt-002", "named", 1),
        ("evt-002", "named", 2),
        ("evt-002", "named", 3),
        ("evt-001", "anon", 1),
        ("evt-002", "anon", 1),
    ]
    assert len(baselines.baseline_units("self_consistency", events)) == 6
    done = BaselineRecord(
        event_id="evt-001",
        variant="named",
        kind="single_k5",
        seed=1,
        k=5,
        n_valid=5,
        score=0.1,
        model="fake-worker",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    pending = baselines.pending_units(single, [done], "single_k5")
    assert len(pending) == 7 and (pending[0].event.event_id, pending[0].seed) == ("evt-001", 2)
    assert len(baselines.pending_units(single, [done], "self_consistency")) == 8


async def test_run_baselines_appends_one_record_per_unit(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    units = baselines.baseline_units("single_k5", make_events(1))[:2]
    provider = FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=lambda **kw: _decision("buy", 0.5))
    written = await baselines.run_baselines(
        "single_k5",
        units,
        provider=provider,
        controller=ImmediateController(),
        config=CONFIG,
        k=5,
        block_for=lambda event, variant: None,
        paths=paths,
    )
    records = read_jsonl(paths.baselines, BaselineRecord)
    assert written == 2 and [r.seed for r in records] == [1, 2]
    assert all(r.score == pytest.approx(0.5) and r.n_valid == 5 and r.k == 5 for r in records)
    assert len(provider.calls) == 10


async def test_run_probes_skips_probed_events(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    answer = json.dumps({"recalled": False, "direction": "unknown", "rationale": ""})
    provider = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake-worker",
        scripted=lambda **kw: InferenceResult(content=answer, model="fake-worker"),
    )
    old = ProbeRecord(
        event_id="evt-001",
        recalled=False,
        direction="unknown",
        parse_failed=False,
        model="fake-worker",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    written = await baselines.run_probes(
        make_events(2),
        provider=provider,
        controller=ImmediateController(),
        config=CONFIG,
        paths=paths,
        existing=[old],
    )
    assert written == 1
    assert [r.event_id for r in read_jsonl(paths.probes, ProbeRecord)] == ["evt-002"]


def test_fixture_block_reads_the_variant_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alphaswarm.ingestion.fixture import anonymize_packet, build_fixture_packet

    paths = EvalPaths(tmp_path)
    event = make_event(1)
    packet = build_fixture_packet(
        event_id="evt-001", as_of=event.timestamp, ticker="ZZZT", close=Decimal("123.45"), volume=1000
    )
    paths.fixtures.mkdir(parents=True)
    paths.fixture("evt-001", "named").write_text(packet.model_dump_json(), encoding="utf-8")
    paths.fixture("evt-001", "anon").write_text(anonymize_packet(packet).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(baselines, "PATHS", paths)
    named = baselines.fixture_block(event, "named")
    anon = baselines.fixture_block(event, "anon")
    assert named is not None and "== ZZZT ==" in named
    assert anon is not None and "ZZZT" not in anon and "Price: $123.45" in anon
