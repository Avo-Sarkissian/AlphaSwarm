"""Tests for AgentWorker and agent_worker context manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.governor import ResourceGovernor
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import AgentWorker, WorkerPersonaConfig, agent_worker


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


@pytest.fixture()
def mock_ollama_client() -> MagicMock:
    """Mock OllamaClient with chat() returning valid JSON response."""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = '{"signal": "buy", "confidence": 0.8}'
    client.chat = AsyncMock(return_value=mock_response)
    return client


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


async def test_semaphore_lifecycle(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """Governor active_count is 1 inside agent_worker, 0 after exit."""
    governor = ResourceGovernor(baseline_parallel=4)
    assert governor.active_count == 0

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        assert governor.active_count == 1

    assert governor.active_count == 0


async def test_semaphore_released_on_error(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """Governor active_count is 0 after exception inside agent_worker."""
    governor = ResourceGovernor(baseline_parallel=4)

    with pytest.raises(RuntimeError, match="test error"):
        async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
            raise RuntimeError("test error")

    assert governor.active_count == 0


async def test_agent_worker_provides_typed_worker(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """agent_worker yields an AgentWorker with infer() method."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        assert isinstance(worker, AgentWorker)
        assert hasattr(worker, "infer")


async def test_infer_returns_agent_decision(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """infer() returns AgentDecision parsed from mocked chat response."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        result = await worker.infer(user_message="AAPL earnings miss")

    assert isinstance(result, AgentDecision)
    assert result.signal == SignalType.BUY


async def test_infer_uses_persona_system_prompt(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """Messages list includes persona system_prompt as role=system."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        await worker.infer(user_message="test")

    call_args = mock_ollama_client.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages") if len(call_args) > 1 else None)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == sample_persona["system_prompt"]


async def test_infer_uses_json_format(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """OllamaClient.chat called with format='json'."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        await worker.infer(user_message="test")

    call_kwargs = mock_ollama_client.chat.call_args.kwargs
    assert call_kwargs.get("format") == "json"


async def test_infer_uses_think_false(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """OllamaClient.chat called with think=False."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        await worker.infer(user_message="test")

    call_kwargs = mock_ollama_client.chat.call_args.kwargs
    assert call_kwargs.get("think") is False


async def test_infer_with_peer_context(
    sample_persona: WorkerPersonaConfig,
    mock_ollama_client: MagicMock,
) -> None:
    """When peer_context provided, messages list has 3 items (system, peer, user)."""
    governor = ResourceGovernor(baseline_parallel=4)

    async with agent_worker(sample_persona, governor, mock_ollama_client) as worker:
        await worker.infer(user_message="test", peer_context="macro_01: SELL")

    call_kwargs = mock_ollama_client.chat.call_args.kwargs
    messages = call_kwargs.get("messages")
    assert len(messages) == 3
    assert "Peer context" in messages[1]["content"]
