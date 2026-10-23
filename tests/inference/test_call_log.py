"""One inference_call line per provider call, numbers only."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from structlog.testing import capture_logs

import alphaswarm.inference.call_log as call_log_module
from alphaswarm.errors import InferenceError
from alphaswarm.inference.call_log import INFERENCE_CALL_EVENT, logged_call
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.logging import pii_redaction_processor
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas, persona_to_worker_config
from alphaswarm.worker import AgentWorker

CYCLE_A = "00000000-0000-4000-8000-0000000000a1"
RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
CONTRACT_FIELDS = frozenset(
    {
        "role",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "prefill_ms",
        "decode_ms",
        "load_ms",
        "finish_reason",
        "latency_ms",
    }
)
REPLY = (
    '{"signal": "buy", "confidence": 0.7, "sentiment": 0.3, '
    '"rationale": "ZZZT deal looks accretive", "cited_agents": []}'
)


@pytest.fixture(autouse=True)
def _fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    # capture_logs cannot see a module logger that an earlier test cached under
    # another structlog configuration; a fresh proxy is never cached here.
    monkeypatch.setattr(call_log_module, "log", structlog.get_logger(component="inference"))


def _calls(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in logs if e["event"] == INFERENCE_CALL_EVENT]


async def test_logged_call_emits_one_line_with_the_contract_fields() -> None:
    result = InferenceResult(
        content=REPLY,
        model="alphaswarm-worker",
        input_tokens=1400,
        output_tokens=150,
        prefill_ms=600.04,
        decode_ms=2700.0,
        load_ms=0.0,
        finish_reason="stop",
    )

    async def call() -> InferenceResult:
        return result

    with capture_logs() as logs:
        out = await logged_call(ProviderRole.WORKER, "alphaswarm-worker", call())
    assert out is result
    [event] = _calls(logs)
    assert event.keys() >= CONTRACT_FIELDS
    assert (event["role"], event["model"], event["prompt_tokens"], event["completion_tokens"]) == (
        "worker",
        "alphaswarm-worker",
        1400,
        150,
    )
    assert (event["prefill_ms"], event["decode_ms"], event["load_ms"]) == (600.0, 2700.0, 0.0)
    assert event["finish_reason"] == "stop"
    assert event["latency_ms"] >= 0.0
    assert "accretive" not in repr(event)  # reply text never reaches the log


async def test_failed_call_logs_error_and_reraises() -> None:
    async def call() -> InferenceResult:
        raise InferenceError("boom", provider="ollama", model="alphaswarm-orchestrator")

    with capture_logs() as logs, pytest.raises(InferenceError):
        await logged_call(ProviderRole.ORCHESTRATOR, "alphaswarm-orchestrator", call())
    [event] = _calls(logs)
    assert (event["role"], event["finish_reason"], event["error_type"]) == (
        "orchestrator",
        "error",
        "InferenceError",
    )
    assert "boom" not in repr(event)  # the exception message never reaches the log


async def test_cancellation_is_not_logged() -> None:
    async def call() -> InferenceResult:
        raise asyncio.CancelledError

    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await logged_call(ProviderRole.WORKER, "alphaswarm-worker", call())
    assert _calls(logs) == []


def test_redaction_keeps_the_token_fields() -> None:
    event = {
        "event": INFERENCE_CALL_EVENT,
        "prompt_tokens": 1400,
        "completion_tokens": 150,
        "cached_prompt_tokens": None,
        "latency_ms": 3.2,
    }
    assert pii_redaction_processor(None, "info", dict(event)) == event


class _FakeOllamaClient:
    async def chat(self, **_: Any) -> Any:
        return SimpleNamespace(
            message=SimpleNamespace(content=REPLY),
            prompt_eval_count=1400,
            prompt_eval_duration=600_000_000,
            eval_count=150,
            eval_duration=2_700_000_000,
            load_duration=0,
            done_reason="stop",
        )


async def test_worker_call_carries_the_run_context() -> None:
    persona = persona_to_worker_config(generate_personas(DEFAULT_BRACKETS)[0])
    provider = OllamaProvider(ProviderRole.WORKER, "alphaswarm-worker", _FakeOllamaClient())  # type: ignore[arg-type]
    with (
        capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs,
        structlog.contextvars.bound_contextvars(cycle_id=CYCLE_A, round=2),
    ):
        await AgentWorker(persona, provider).infer(user_message=RUMOR)
    [event] = _calls(logs)
    assert (event["cycle_id"], event["round"], event["agent_id"]) == (CYCLE_A, 2, persona["agent_id"])
    assert event["prompt_tokens"] == 1400
