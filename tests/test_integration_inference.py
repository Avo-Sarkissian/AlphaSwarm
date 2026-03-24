"""Integration test: module integration for Phase 2 inference pipeline.

Uses mocked AsyncClient to verify the full inference path without
a running Ollama server. The integration here is between modules
(governor + client + parsing + worker + model_manager), not with external services.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.governor import ResourceGovernor
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.ollama_models import OllamaModelManager
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import AgentWorker, WorkerPersonaConfig, agent_worker


@pytest.fixture()
def persona() -> WorkerPersonaConfig:
    return WorkerPersonaConfig(
        agent_id="quant_01",
        bracket="quants",
        influence_weight=0.7,
        temperature=0.3,
        system_prompt="You are a quantitative analyst. Analyze data and form opinions.",
        risk_profile="0.4",
    )


def _make_mock_client(response_content: str) -> OllamaClient:
    """Create an OllamaClient with mocked internal client."""
    client = OllamaClient.__new__(OllamaClient)
    mock_inner = AsyncMock()
    mock_response = MagicMock()
    mock_response.message.content = response_content
    mock_inner.chat.return_value = mock_response
    client._client = mock_inner
    client._base_url = "http://localhost:11434"
    return client


@pytest.fixture()
def mock_client_success() -> OllamaClient:
    """OllamaClient returning valid JSON."""
    return _make_mock_client(
        '{"signal": "sell", "confidence": 0.72, "sentiment": -0.3, '
        '"rationale": "Earnings miss suggests downside", "cited_agents": []}'
    )


@pytest.fixture()
def mock_client_garbled() -> OllamaClient:
    """OllamaClient returning unparseable output."""
    return _make_mock_client(
        "I think the market will go up but I am not sure about anything really."
    )


async def test_single_agent_inference(
    persona: WorkerPersonaConfig,
    mock_client_success: OllamaClient,
) -> None:
    """Full path: acquire governor, infer via agent_worker, parse AgentDecision, release."""
    governor = ResourceGovernor(baseline_parallel=8)
    assert governor.active_count == 0

    async with agent_worker(persona, governor, mock_client_success, model="alphaswarm-worker") as worker:
        assert governor.active_count == 1
        decision = await worker.infer(
            user_message="BREAKING: Apple reports Q3 earnings miss, revenue down 5% YoY"
        )

    # Verify decision
    assert isinstance(decision, AgentDecision)
    assert decision.signal == SignalType.SELL
    assert decision.confidence == 0.72
    assert decision.sentiment == -0.3
    assert "Earnings miss" in decision.rationale

    # Verify governor released
    assert governor.active_count == 0

    # Verify OllamaClient was called correctly
    mock_client_success._client.chat.assert_called_once()
    call_kwargs = mock_client_success._client.chat.call_args.kwargs
    assert call_kwargs.get("format") == "json"
    assert call_kwargs.get("think") is False
    assert call_kwargs.get("model") == "alphaswarm-worker"


async def test_inference_parse_error_fallback(
    persona: WorkerPersonaConfig,
    mock_client_garbled: OllamaClient,
) -> None:
    """Agent inference with garbled response falls back to PARSE_ERROR."""
    governor = ResourceGovernor(baseline_parallel=8)

    async with agent_worker(persona, governor, mock_client_garbled, model="alphaswarm-worker") as worker:
        decision = await worker.infer(
            user_message="BREAKING: Apple reports Q3 earnings miss"
        )

    assert isinstance(decision, AgentDecision)
    assert decision.signal == SignalType.PARSE_ERROR
    assert decision.confidence == 0.0
    assert decision.rationale.startswith("Parse failed:")

    # Governor still released
    assert governor.active_count == 0


async def test_inference_with_peer_context(
    persona: WorkerPersonaConfig,
    mock_client_success: OllamaClient,
) -> None:
    """Agent inference includes peer context in messages when provided."""
    governor = ResourceGovernor(baseline_parallel=8)

    async with agent_worker(persona, governor, mock_client_success, model="alphaswarm-worker") as worker:
        decision = await worker.infer(
            user_message="BREAKING: Apple reports Q3 earnings miss",
            peer_context="macro_01: SELL (confidence=0.9), suits_03: HOLD (confidence=0.6)",
        )

    assert isinstance(decision, AgentDecision)

    # Verify peer context was included in messages
    call_kwargs = mock_client_success._client.chat.call_args.kwargs
    messages = call_kwargs.get("messages")
    # Should have 3 messages: system prompt, peer context, user message
    assert len(messages) == 3
    assert "Peer context" in messages[1]["content"]


async def test_governor_backpressure(
    persona: WorkerPersonaConfig,
    mock_client_success: OllamaClient,
) -> None:
    """Governor with 1 slot blocks second concurrent agent_worker entry."""
    governor = ResourceGovernor(baseline_parallel=1)
    order: list[str] = []

    async def first_worker() -> None:
        async with agent_worker(persona, governor, mock_client_success, model="alphaswarm-worker") as w:
            order.append("first_acquired")
            await asyncio.sleep(0.1)  # Hold the slot briefly
            await w.infer(user_message="test")
            order.append("first_done")

    async def second_worker() -> None:
        await asyncio.sleep(0.01)  # Ensure first_worker starts first
        async with agent_worker(persona, governor, mock_client_success, model="alphaswarm-worker") as w:
            order.append("second_acquired")
            await w.infer(user_message="test")
            order.append("second_done")

    await asyncio.gather(first_worker(), second_worker())

    # First worker must complete before second acquires
    assert order.index("first_acquired") < order.index("second_acquired")
    assert governor.active_count == 0


async def test_sequential_model_flow() -> None:
    """Orchestrator -> unload -> worker sequential flow with mocked clients.

    This is the Phase 2 Success Criterion 1: orchestrator model loads,
    unloads before worker loads. Addresses HIGH review concern from both
    Gemini and Codex that this flow was never verified.
    """
    # Create a mock OllamaClient
    client = OllamaClient.__new__(OllamaClient)
    mock_inner = AsyncMock()

    # Track model state to simulate load/unload
    loaded_models: list[str] = []

    async def mock_chat(**kwargs):  # type: ignore[no-untyped-def]
        model = kwargs.get("model", "")
        keep_alive = kwargs.get("keep_alive")
        messages = kwargs.get("messages", [])

        if keep_alive == 0:
            # Unload request
            if model in loaded_models:
                loaded_models.remove(model)
        elif messages:
            # Load/inference request
            if model not in loaded_models:
                loaded_models.append(model)

        response = MagicMock()
        response.message.content = '{"signal": "buy", "confidence": 0.8}'
        return response

    mock_inner.chat = AsyncMock(side_effect=mock_chat)

    # ps() returns currently loaded models
    async def mock_ps():  # type: ignore[no-untyped-def]
        ps_response = MagicMock()
        ps_models = []
        for m in loaded_models:
            pm = MagicMock()
            pm.model = m
            ps_models.append(pm)
        ps_response.models = ps_models
        return ps_response

    mock_inner.ps = AsyncMock(side_effect=mock_ps)

    client._client = mock_inner
    client._base_url = "http://localhost:11434"

    # Create model manager with configured aliases
    manager = OllamaModelManager(
        client=client,
        configured_aliases={"alphaswarm-orchestrator", "alphaswarm-worker"},
    )

    # Step 1: Load orchestrator
    await manager.load_model("alphaswarm-orchestrator")
    assert manager.current_model == "alphaswarm-orchestrator"
    assert "alphaswarm-orchestrator" in loaded_models
    assert "alphaswarm-worker" not in loaded_models

    # Step 2: Unload orchestrator
    await manager.unload_model("alphaswarm-orchestrator")
    assert manager.current_model is None
    assert "alphaswarm-orchestrator" not in loaded_models

    # Step 3: Load worker
    await manager.load_model("alphaswarm-worker")
    assert manager.current_model == "alphaswarm-worker"
    assert "alphaswarm-worker" in loaded_models
    assert "alphaswarm-orchestrator" not in loaded_models  # Still unloaded

    # Step 4: Clean up
    await manager.ensure_clean_state()
    assert len(loaded_models) == 0
    assert manager.current_model is None


async def test_ensure_clean_state_scoped_in_integration() -> None:
    """ensure_clean_state does NOT unload unrelated models.

    Addresses review concern: ensure_clean_state was too broad.
    """
    client = OllamaClient.__new__(OllamaClient)
    mock_inner = AsyncMock()

    loaded_models = ["alphaswarm-worker", "codellama:7b", "alphaswarm-orchestrator"]
    unloaded: list[str] = []

    async def mock_chat(**kwargs):  # type: ignore[no-untyped-def]
        model = kwargs.get("model", "")
        keep_alive = kwargs.get("keep_alive")
        if keep_alive == 0 and model in loaded_models:
            loaded_models.remove(model)
            unloaded.append(model)
        response = MagicMock()
        response.message.content = ""
        return response

    mock_inner.chat = AsyncMock(side_effect=mock_chat)

    async def mock_ps():  # type: ignore[no-untyped-def]
        ps_response = MagicMock()
        ps_models = []
        for m in loaded_models:
            pm = MagicMock()
            pm.model = m
            ps_models.append(pm)
        ps_response.models = ps_models
        return ps_response

    mock_inner.ps = AsyncMock(side_effect=mock_ps)
    client._client = mock_inner
    client._base_url = "http://localhost:11434"

    manager = OllamaModelManager(
        client=client,
        configured_aliases={"alphaswarm-orchestrator", "alphaswarm-worker"},
    )

    await manager.ensure_clean_state()

    # alphaswarm models unloaded
    assert "alphaswarm-worker" in unloaded
    assert "alphaswarm-orchestrator" in unloaded

    # codellama NOT unloaded
    assert "codellama:7b" not in unloaded
    assert "codellama:7b" in loaded_models
