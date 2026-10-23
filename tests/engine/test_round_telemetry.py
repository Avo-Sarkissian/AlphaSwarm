"""Round telemetry reaches the cycle metrics through the real round runner."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

import alphaswarm.rounds as rounds_module
from alphaswarm.inference.types import InferenceResult
from alphaswarm.types import AgentPersona
from tests.engine.scenario import RecordingStateStore, RunScenario, recorded_decisions
from tests.inference.fakes import ScriptedCall, ScriptedProvider

TELEMETRY_SUFFIXES = (
    "latency_p50_ms",
    "latency_p95_ms",
    "mean_prompt_tokens",
    "mean_completion_tokens",
    "mean_prefill_ms",
    "mean_decode_ms",
    "total_load_ms",
    "cold_loads",
    "truncations",
    "ctx_warnings",
)
TRUNCATED_JSON = '{"signal": "buy", "confidence": 0.8, "rationale": "The ZZZT deal'


def _metrics(fake_graph: MagicMock) -> dict[str, object]:
    return dict(fake_graph.write_cycle_metrics.await_args.args[1])


def _worker(
    personas: list[AgentPersona], store: RecordingStateStore, hook: object, *, is_local: bool = True
) -> ScriptedProvider:
    return ScriptedProvider(
        personas=personas,
        round_source=lambda: store.snapshot().round_num,
        result_hook=hook,  # type: ignore[arg-type]
        is_local=is_local,
    )


async def test_round_telemetry_reaches_the_cycle_metrics(run_scenario: RunScenario, fake_graph: MagicMock) -> None:
    await run_scenario()
    m = _metrics(fake_graph)
    for n in (1, 2, 3):
        assert (m[f"r{n}_mean_prompt_tokens"], m[f"r{n}_mean_completion_tokens"]) == (1400.0, 150.0)
        assert (m[f"r{n}_mean_prefill_ms"], m[f"r{n}_mean_decode_ms"]) == (600.0, 2700.0)
        assert m[f"r{n}_total_load_ms"] == 0.0
        assert (m[f"r{n}_cold_loads"], m[f"r{n}_truncations"], m[f"r{n}_ctx_warnings"]) == (0, 0, 0)
        p50, p95 = m[f"r{n}_latency_p50_ms"], m[f"r{n}_latency_p95_ms"]
        assert isinstance(p50, float) and isinstance(p95, float)
        assert p95 >= p50 >= 0.0


async def test_two_rounds_write_no_round_three_telemetry(run_scenario: RunScenario, fake_graph: MagicMock) -> None:
    await run_scenario(num_rounds=2)
    m = _metrics(fake_graph)
    assert not [k for k in m if k.startswith("r3_") and k.removeprefix("r3_") in TELEMETRY_SUFFIXES]
    assert m["r2_mean_prompt_tokens"] == 1400.0


async def test_truncations_reach_the_cycle_metrics(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    cut = {all_personas[0].id, all_personas[1].id}

    def hook(call: ScriptedCall, result: InferenceResult) -> InferenceResult:
        if call.round_num == 2 and call.agent_id in cut:
            return dataclasses.replace(result, content=TRUNCATED_JSON, finish_reason="length")
        return result

    await run_scenario(worker=_worker(all_personas, scenario_store, hook))
    m = _metrics(fake_graph)
    assert (m["r1_truncations"], m["r2_truncations"], m["r3_truncations"]) == (0, 2, 0)
    parse_errors = m["r2_parse_errors"]
    assert isinstance(parse_errors, int) and parse_errors >= 2
    kinds = {aid: d.error_kind for aid, d in recorded_decisions(fake_graph)[2] if aid in cut}
    assert kinds == dict.fromkeys(cut, "truncated")


async def test_prompts_near_the_context_limit_are_flagged(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fresh logger proxy: capture_logs cannot see a module logger that an earlier
    # test cached under another structlog configuration.
    monkeypatch.setattr(rounds_module, "logger", structlog.get_logger(component="rounds"))

    def hook(call: ScriptedCall, result: InferenceResult) -> InferenceResult:
        return dataclasses.replace(result, input_tokens=4000) if call.round_num == 1 else result

    with capture_logs() as logs:
        await run_scenario(worker=_worker(all_personas, scenario_store, hook))
    m = _metrics(fake_graph)
    assert (m["r1_ctx_warnings"], m["r2_ctx_warnings"]) == (100, 0)  # 4000 >= 0.9 * 4096
    warned = [e for e in logs if e["event"] == "prompt_near_context_limit"]
    assert [(e["round_num"], e["calls"], e["num_ctx"]) for e in warned] == [(1, 100, 4096)]


async def test_cloud_workers_get_no_context_warnings(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    def hook(call: ScriptedCall, result: InferenceResult) -> InferenceResult:
        return dataclasses.replace(result, input_tokens=4000)

    await run_scenario(worker=_worker(all_personas, scenario_store, hook, is_local=False))
    assert _metrics(fake_graph)["r1_ctx_warnings"] == 0
