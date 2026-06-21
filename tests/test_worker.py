"""Tests for AgentWorker and agent_worker context manager."""

from __future__ import annotations

import pytest

from alphaswarm.config import GovernorSettings
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA, AgentWorker, WorkerPersonaConfig, agent_worker
from tests.inference.fakes import FakeInferenceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_BUY_JSON = (
    '{"signal": "buy", "confidence": 0.8, "sentiment": 0.4, '
    '"rationale": "strong momentum", "cited_agents": []}'
)

_VALID_HOLD_JSON = (
    '{"signal": "hold", "confidence": 0.5, "sentiment": 0.0, '
    '"rationale": "neutral", "cited_agents": []}'
)


def _fake_provider(content: str = _VALID_BUY_JSON, *, n: int = 1) -> FakeInferenceProvider:
    """Return a FakeInferenceProvider scripted with n identical results."""
    scripted = [
        InferenceResult(
            content=content,
            model="fake-model",
            eval_count=50,
            eval_duration_ns=1_000_000_000,
        )
        for _ in range(n)
    ]
    return FakeInferenceProvider(
        role=ProviderRole.WORKER,
        model="fake-model",
        scripted=scripted,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_persona() -> WorkerPersonaConfig:
    return WorkerPersonaConfig(
        agent_id="quant_01",
        bracket="quants",
        influence_weight=0.7,
        temperature=0.3,
        system_prompt="You are a quantitative analyst.",
        risk_profile="0.4",
    )


# ---------------------------------------------------------------------------
# TypedDict field contract
# ---------------------------------------------------------------------------


def test_worker_persona_config_fields() -> None:
    """WorkerPersonaConfig has all expected TypedDict fields."""
    config = WorkerPersonaConfig(
        agent_id="quant_01",
        bracket="quants",
        influence_weight=0.7,
        temperature=0.3,
        system_prompt="You are a quantitative analyst.",
        risk_profile="0.4",
    )
    assert config["agent_id"] == "quant_01"
    assert config["bracket"] == "quants"
    assert config["influence_weight"] == 0.7
    assert config["temperature"] == 0.3
    assert config["system_prompt"] == "You are a quantitative analyst."
    assert config["risk_profile"] == "0.4"


# ---------------------------------------------------------------------------
# agent_worker semaphore lifecycle
# ---------------------------------------------------------------------------


async def test_semaphore_lifecycle(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Governor active_count is 1 inside agent_worker, 0 after exit."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()
    assert governor.active_count == 0

    async with agent_worker(sample_persona, governor, provider) as worker:
        assert governor.active_count == 1

    assert governor.active_count == 0


async def test_semaphore_released_on_error(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Governor active_count is 0 after exception inside agent_worker."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    with pytest.raises(RuntimeError, match="test error"):
        async with agent_worker(sample_persona, governor, provider) as worker:
            raise RuntimeError("test error")

    assert governor.active_count == 0


async def test_agent_worker_provides_typed_worker(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """agent_worker yields an AgentWorker with infer() method."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        assert isinstance(worker, AgentWorker)
        assert hasattr(worker, "infer")


# ---------------------------------------------------------------------------
# infer() behaviour
# ---------------------------------------------------------------------------


async def test_infer_returns_agent_decision(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """infer() returns AgentDecision parsed from provider result."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        result = await worker.infer(user_message="AAPL earnings miss")

    assert isinstance(result, AgentDecision)
    assert result.signal == SignalType.BUY


async def test_infer_uses_persona_system_prompt(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Messages list includes persona system_prompt as role=system."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test")

    call = provider.calls[0]
    messages = call["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == sample_persona["system_prompt"]


async def test_infer_uses_json_schema(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Provider.chat called with response_schema=DECISION_JSON_SCHEMA."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test")

    call = provider.calls[0]
    assert call["response_schema"] == DECISION_JSON_SCHEMA


async def test_infer_uses_persona_temperature(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Provider.chat called with temperature=persona['temperature']."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test")

    call = provider.calls[0]
    assert call["temperature"] == sample_persona["temperature"]


async def test_infer_with_peer_context(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """When peer_context provided, messages list has 3 items (system, peer, user)."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test", peer_context="macro_01: SELL")

    messages = provider.calls[0]["messages"]
    assert len(messages) == 3
    assert "Peer context" in messages[1]["content"]


async def test_infer_with_market_context(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Phase 40 D-04: market_context injected as system msg before user msg."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test", market_context="Market context body")

    messages = provider.calls[0]["messages"]
    assert len(messages) == 3
    assert messages[1]["role"] == "system"
    assert messages[1]["content"] == "Market context:\nMarket context body"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "test"


async def test_infer_with_market_and_peer_context(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """Phase 40 D-04: market_context comes before peer_context when both present."""
    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    provider = _fake_provider()

    async with agent_worker(sample_persona, governor, provider) as worker:
        await worker.infer(user_message="test", market_context="MKT", peer_context="PEER")

    messages = provider.calls[0]["messages"]
    assert len(messages) == 4
    assert messages[1]["content"] == "Market context:\nMKT"
    assert messages[2]["content"] == "Peer context:\nPEER"
    assert messages[3]["content"] == "test"


# ---------------------------------------------------------------------------
# Task 4: InferenceProvider-based AgentWorker (RED test written first, then GREEN)
# ---------------------------------------------------------------------------


async def test_agent_worker_with_fake_provider_returns_parsed_decision(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """AgentWorker(FakeInferenceProvider).infer() returns a parsed AgentDecision.

    Asserts:
    - provider received response_schema=DECISION_JSON_SCHEMA
    - provider received temperature=sample_persona["temperature"]
    - return value is a parsed AgentDecision (not PARSE_ERROR)
    """
    scripted_result = InferenceResult(
        content=(
            '{"signal": "buy", "confidence": 0.75, "sentiment": 0.5, '
            '"rationale": "strong upward momentum", "cited_agents": []}'
        ),
        model="fake-model",
        eval_count=42,
        eval_duration_ns=1_000_000_000,
    )

    provider = FakeInferenceProvider(
        role=ProviderRole.WORKER,
        model="fake-model",
        scripted=[scripted_result],
    )

    worker = AgentWorker(sample_persona, provider)
    decision = await worker.infer(user_message="AAPL rumor")

    # Decision must be a real parsed signal, not PARSE_ERROR
    assert isinstance(decision, AgentDecision)
    assert decision.signal == SignalType.BUY

    # Provider must have received the right schema and temperature
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["response_schema"] == DECISION_JSON_SCHEMA
    assert call["temperature"] == sample_persona["temperature"]


async def test_agent_worker_context_manager_with_provider(
    sample_persona: WorkerPersonaConfig,
) -> None:
    """agent_worker() context manager accepts provider and tracks semaphore."""
    scripted_result = InferenceResult(
        content=(
            '{"signal": "hold", "confidence": 0.5, "sentiment": 0.0, '
            '"rationale": "neutral", "cited_agents": []}'
        ),
        model="fake-model",
    )

    provider = FakeInferenceProvider(
        role=ProviderRole.WORKER,
        model="fake-model",
        scripted=[scripted_result],
    )

    governor = ResourceGovernor(GovernorSettings(baseline_parallel=4))
    assert governor.active_count == 0

    async with agent_worker(sample_persona, governor, provider) as worker:
        assert governor.active_count == 1
        decision = await worker.infer(user_message="test")

    assert governor.active_count == 0
    assert isinstance(decision, AgentDecision)
    assert decision.signal == SignalType.HOLD
