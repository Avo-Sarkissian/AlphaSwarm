"""Unit tests for OllamaModelManager (INFRA-03).

Tests verify:
- Model unloading via keep_alive=0
- Model loaded status via ps()
- Sequential load/unload lifecycle
- ModelLoadError on failed load
- ensure_clean_state scoped to configured aliases only
- Lock serialization of concurrent operations
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.errors import ModelLoadError


def _make_process_model(name: str) -> MagicMock:
    """Create a mock ProcessModel with .model attribute."""
    m = MagicMock()
    m.model = name
    return m


def _make_ps_response(model_names: list[str]) -> MagicMock:
    """Create a mock ProcessResponse with .models list."""
    resp = MagicMock()
    resp.models = [_make_process_model(n) for n in model_names]
    return resp


@pytest.fixture()
def mock_raw_client() -> AsyncMock:
    """Create a mocked raw ollama.AsyncClient."""
    client = AsyncMock()
    client.chat = AsyncMock()
    client.ps = AsyncMock(return_value=_make_ps_response([]))
    return client


@pytest.fixture()
def mock_ollama_client(mock_raw_client: AsyncMock) -> MagicMock:
    """Create a mocked OllamaClient with _client and raw_client."""
    from alphaswarm.ollama_client import OllamaClient

    oc = MagicMock(spec=OllamaClient)
    oc._client = mock_raw_client
    oc.raw_client = mock_raw_client
    # Make chat an async mock that delegates to raw client
    oc.chat = AsyncMock()
    return oc


@pytest.fixture()
def model_manager(mock_ollama_client: MagicMock) -> Any:
    """Create an OllamaModelManager with mocked OllamaClient."""
    from alphaswarm.ollama_models import OllamaModelManager

    return OllamaModelManager(
        client=mock_ollama_client,
        configured_aliases={"alphaswarm-orchestrator", "alphaswarm-worker"},
    )


async def test_unload_model(
    model_manager: Any, mock_ollama_client: MagicMock
) -> None:
    """unload_model() calls client.chat() with model=tag, messages=[], keep_alive=0."""
    await model_manager.unload_model("qwen3.5:32b")
    mock_ollama_client.chat.assert_called_once_with(
        model="qwen3.5:32b",
        messages=[],
        keep_alive=0,
    )


async def test_verify_unloaded(
    model_manager: Any, mock_raw_client: AsyncMock
) -> None:
    """Mocked ps() returns empty models list, is_model_loaded returns False."""
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response([]))
    result = await model_manager.is_model_loaded("qwen3.5:32b")
    assert result is False


async def test_verify_loaded(
    model_manager: Any, mock_raw_client: AsyncMock
) -> None:
    """Mocked ps() returns model in list, is_model_loaded returns True."""
    mock_raw_client.ps = AsyncMock(
        return_value=_make_ps_response(["qwen3.5:32b"])
    )
    result = await model_manager.is_model_loaded("qwen3.5:32b")
    assert result is True


async def test_sequential_load(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    """Load orchestrator -> verify -> unload -> verify -> load worker -> verify."""
    # ps() returns the loaded model after each load call
    mock_raw_client.ps = AsyncMock(
        side_effect=[
            _make_ps_response(["alphaswarm-orchestrator"]),  # after load orch
            _make_ps_response([]),  # after unload orch
            _make_ps_response(["alphaswarm-worker"]),  # after load worker
        ]
    )
    await model_manager.load_model("alphaswarm-orchestrator")
    assert model_manager.current_model == "alphaswarm-orchestrator"

    await model_manager.unload_model("alphaswarm-orchestrator")
    assert model_manager.current_model is None

    await model_manager.load_model("alphaswarm-worker")
    assert model_manager.current_model == "alphaswarm-worker"


async def test_load_failure_raises_model_load_error(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    """When ps() never shows model loaded, raises ModelLoadError."""
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response([]))
    with pytest.raises(ModelLoadError):
        await model_manager.load_model("alphaswarm-orchestrator")


async def test_ensure_clean_state_scoped(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    """ensure_clean_state only unloads configured aliases, not unrelated models."""
    mock_raw_client.ps = AsyncMock(
        return_value=_make_ps_response([
            "alphaswarm-orchestrator",
            "alphaswarm-worker",
            "codellama:7b",
        ])
    )
    await model_manager.ensure_clean_state()

    # Check which models were unloaded
    unload_calls = mock_ollama_client.chat.call_args_list
    unloaded_models = [call.kwargs.get("model") or call[1].get("model") for call in unload_calls]
    assert "alphaswarm-orchestrator" in unloaded_models
    assert "alphaswarm-worker" in unloaded_models
    assert "codellama:7b" not in unloaded_models


async def test_load_unload_serialized(
    mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    """Concurrent load/unload calls are serialized by internal Lock."""
    from alphaswarm.ollama_models import OllamaModelManager

    call_order: list[str] = []

    async def track_chat(**kwargs: Any) -> MagicMock:
        model = kwargs.get("model", "unknown")
        call_order.append(f"start:{model}")
        await asyncio.sleep(0.05)  # Simulate async work
        call_order.append(f"end:{model}")
        return MagicMock()

    mock_ollama_client.chat = AsyncMock(side_effect=track_chat)
    mock_raw_client.ps = AsyncMock(
        return_value=_make_ps_response(["model-a", "model-b"])
    )

    manager = OllamaModelManager(
        client=mock_ollama_client,
        configured_aliases={"model-a", "model-b"},
    )

    # Run two operations concurrently
    await asyncio.gather(
        manager.load_model("model-a"),
        manager.unload_model("model-b"),
    )

    # Verify serialization: one operation must complete before the next starts
    # With the lock, we should see: start:A, end:A, start:B, end:B (or reverse)
    # Without the lock, we'd see interleaving: start:A, start:B, ...
    assert len(call_order) == 4
    # The first operation should complete (start+end) before the second starts
    first_start_idx = 0
    first_end_idx = 1
    second_start_idx = 2
    assert call_order[first_start_idx].startswith("start:")
    assert call_order[first_end_idx].startswith("end:")
    assert call_order[second_start_idx].startswith("start:")
    # First op's model should match between start and end
    first_model = call_order[first_start_idx].split(":")[1]
    assert call_order[first_end_idx] == f"end:{first_model}"
