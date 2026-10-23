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
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import alphaswarm.ollama_models as ollama_models_module
from alphaswarm.errors import ModelLoadError
from alphaswarm.ollama_models import WARMUP_PROMPT, WARMUP_SLOW_PREFILL_TPS, warmup_stats


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
        unload_timeout_s=0.05,
        poll_interval_s=0.0,
    )


async def test_unload_model(model_manager: Any, mock_ollama_client: MagicMock) -> None:
    """unload_model() calls client.chat() with model=tag, messages=[], keep_alive=0."""
    await model_manager.unload_model("qwen3.5:32b")
    mock_ollama_client.chat.assert_called_once_with(
        model="qwen3.5:32b",
        messages=[],
        keep_alive=0,
    )


async def test_verify_unloaded(model_manager: Any, mock_raw_client: AsyncMock) -> None:
    """Mocked ps() returns empty models list, is_model_loaded returns False."""
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response([]))
    result = await model_manager.is_model_loaded("qwen3.5:32b")
    assert result is False


async def test_verify_loaded(model_manager: Any, mock_raw_client: AsyncMock) -> None:
    """Mocked ps() returns model in list, is_model_loaded returns True."""
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response(["qwen3.5:32b"]))
    result = await model_manager.is_model_loaded("qwen3.5:32b")
    assert result is True


async def test_sequential_load(model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock) -> None:
    """Load orchestrator -> unload it -> load worker; ps() verifies every load and unload."""
    mock_raw_client.ps = AsyncMock(
        side_effect=[
            _make_ps_response(["alphaswarm-orchestrator"]),  # load(orch): verify loaded
            _make_ps_response([]),  # unload(orch): verify gone
            _make_ps_response(["alphaswarm-worker"]),  # load(worker): verify loaded
        ]
    )
    await model_manager.load_model("alphaswarm-orchestrator")
    await model_manager.unload_model("alphaswarm-orchestrator")
    await model_manager.load_model("alphaswarm-worker")

    calls = [(c.kwargs["model"], c.kwargs["keep_alive"]) for c in mock_ollama_client.chat.await_args_list]
    assert calls == [
        ("alphaswarm-orchestrator", "5m"),
        ("alphaswarm-orchestrator", 0),
        ("alphaswarm-worker", "5m"),
    ]
    assert mock_raw_client.ps.await_count == 3


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
        return_value=_make_ps_response(
            [
                "alphaswarm-orchestrator",
                "alphaswarm-worker",
                "codellama:7b",
            ]
        )
    )
    await model_manager.ensure_clean_state()

    # Check which models were unloaded
    unload_calls = mock_ollama_client.chat.call_args_list
    unloaded_models = [call.kwargs.get("model") or call[1].get("model") for call in unload_calls]
    assert "alphaswarm-orchestrator" in unloaded_models
    assert "alphaswarm-worker" in unloaded_models
    assert "codellama:7b" not in unloaded_models


async def test_load_unload_serialized(mock_ollama_client: MagicMock, mock_raw_client: AsyncMock) -> None:
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
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response(["model-a", "model-b"]))

    manager = OllamaModelManager(
        client=mock_ollama_client,
        configured_aliases={"model-a", "model-b"},
        unload_timeout_s=0.05,
        poll_interval_s=0.0,
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


def _nameless_entry() -> MagicMock:
    entry = MagicMock()
    entry.model = None  # ollama's ProcessModel.model is Optional[str]
    return entry


async def test_is_model_loaded_ignores_entries_without_a_name(model_manager: Any, mock_raw_client: AsyncMock) -> None:
    response = _make_ps_response(["alphaswarm-worker"])
    response.models.append(_nameless_entry())
    mock_raw_client.ps = AsyncMock(return_value=response)
    assert await model_manager.is_model_loaded("alphaswarm-worker") is True


async def test_ensure_clean_state_ignores_entries_without_a_name(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    response = _make_ps_response(["alphaswarm-worker"])
    response.models.insert(0, _nameless_entry())
    mock_raw_client.ps = AsyncMock(return_value=response)
    await model_manager.ensure_clean_state()
    assert [c.kwargs["model"] for c in mock_ollama_client.chat.call_args_list] == ["alphaswarm-worker"]


def test_model_manager_no_longer_tracks_a_current_model() -> None:
    """current_model was write-only bookkeeping; ps() is the source of truth."""
    from alphaswarm.ollama_models import OllamaModelManager

    assert not hasattr(OllamaModelManager, "current_model")


async def test_loaded_models_lists_every_resident_model(model_manager: Any, mock_raw_client: AsyncMock) -> None:
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response(["llama3:8b", "alphaswarm-worker"]))
    assert await model_manager.loaded_models() == ["alphaswarm-worker", "llama3:8b"]


class _WarmupLog:
    """Stand-in for the module logger; records (event, fields) for every level used."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def ainfo(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    async def awarning(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def named(self, event: str) -> list[dict[str, Any]]:
        return [fields for name, fields in self.events if name == event]


@pytest.fixture()
def warmup_log(monkeypatch: pytest.MonkeyPatch) -> _WarmupLog:
    rec = _WarmupLog()
    monkeypatch.setattr(ollama_models_module, "logger", rec)
    return rec


def _resident(mock_raw_client: AsyncMock, model: str) -> None:
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response([model]))


async def test_warmup_request_shape(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    _resident(mock_raw_client, "alphaswarm-orchestrator")
    await model_manager.load_model("alphaswarm-orchestrator")
    assert mock_ollama_client.chat.await_args.kwargs == {
        "model": "alphaswarm-orchestrator",
        "messages": [{"role": "user", "content": WARMUP_PROMPT}],
        "think": False,
        "keep_alive": "5m",
        "options": {"num_predict": 1},
        "timeout_role": "orchestrator",
    }


async def test_warmup_uses_the_long_read_timeout(
    model_manager: Any, mock_ollama_client: MagicMock, mock_raw_client: AsyncMock
) -> None:
    # Loading the worker pays model load plus MLX kernel compilation, so the
    # warm-up must never run on the 120 s worker read timeout.
    _resident(mock_raw_client, "alphaswarm-worker")
    await model_manager.load_model("alphaswarm-worker")
    kwargs = mock_ollama_client.chat.await_args.kwargs
    assert kwargs["timeout_role"] == "orchestrator"
    assert kwargs["messages"] and kwargs["messages"][0]["content"].strip()


async def test_warmup_logs_load_and_prefill(
    model_manager: Any,
    mock_ollama_client: MagicMock,
    mock_raw_client: AsyncMock,
    warmup_log: _WarmupLog,
) -> None:
    _resident(mock_raw_client, "alphaswarm-worker")
    mock_ollama_client.chat.return_value = SimpleNamespace(
        prompt_eval_count=40, prompt_eval_duration=20_000_000, load_duration=1_500_000_000
    )
    await model_manager.load_model("alphaswarm-worker")
    [fields] = warmup_log.named("model_warmed")
    assert fields["model"] == "alphaswarm-worker"
    assert (fields["prompt_tokens"], fields["prefill_tps"], fields["load_ms"]) == (40, 2000.0, 1500.0)
    assert fields["warmup_ms"] >= 0.0
    assert warmup_log.named("model_warmup_slow") == []


async def test_slow_warmup_prefill_warns(
    model_manager: Any,
    mock_ollama_client: MagicMock,
    mock_raw_client: AsyncMock,
    warmup_log: _WarmupLog,
) -> None:
    _resident(mock_raw_client, "alphaswarm-orchestrator")
    half_rate = WARMUP_SLOW_PREFILL_TPS / 2  # 100 t/s at the shipped 200 t/s threshold
    mock_ollama_client.chat.return_value = SimpleNamespace(
        prompt_eval_count=40, prompt_eval_duration=int(40 / half_rate * 1e9), load_duration=0
    )
    await model_manager.load_model("alphaswarm-orchestrator")
    [fields] = warmup_log.named("model_warmup_slow")
    assert (fields["model"], fields["prefill_tps"], fields["threshold_tps"]) == (
        "alphaswarm-orchestrator",
        round(half_rate, 1),
        WARMUP_SLOW_PREFILL_TPS,
    )


def test_warmup_stats_tolerate_missing_fields() -> None:
    assert warmup_stats(MagicMock(), 0.25) == {
        "warmup_ms": 250.0,
        "load_ms": None,
        "prompt_tokens": None,
        "prefill_tps": None,
    }


class _RecordingLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def ainfo(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))

    async def awarning(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))

    def warning(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


async def test_unload_waits_until_ps_no_longer_lists_the_model(
    model_manager: Any, mock_raw_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _RecordingLog()
    monkeypatch.setattr("alphaswarm.ollama_models.logger", rec)
    mock_raw_client.ps = AsyncMock(
        side_effect=[
            _make_ps_response(["alphaswarm-worker"]),
            _make_ps_response(["alphaswarm-worker"]),
            _make_ps_response([]),
        ]
    )
    await model_manager.unload_model("alphaswarm-worker")
    assert mock_raw_client.ps.await_count == 3
    unloaded = [kw for e, kw in rec.events if e == "model_unloaded"]
    assert len(unloaded) == 1 and isinstance(unloaded[0]["unload_ms"], int)


async def test_unload_gives_up_after_the_timeout_and_warns(
    model_manager: Any, mock_raw_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _RecordingLog()
    monkeypatch.setattr("alphaswarm.ollama_models.logger", rec)
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response(["alphaswarm-worker"]))
    await model_manager.unload_model("alphaswarm-worker")
    unload_events = [e for e, _ in rec.events if e.startswith("model_unload")]
    assert unload_events[-1] == "model_unload_unverified"
    assert "model_unloaded" not in unload_events


async def test_unload_check_failure_is_logged_not_raised(
    model_manager: Any, mock_raw_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _RecordingLog()
    monkeypatch.setattr("alphaswarm.ollama_models.logger", rec)
    mock_raw_client.ps = AsyncMock(side_effect=ConnectionError("refused"))
    await model_manager.unload_model("alphaswarm-worker")
    events = [e for e, _ in rec.events]
    assert "model_unload_check_failed" in events and events[-1] == "model_unload_unverified"


async def test_load_logs_load_ms(
    model_manager: Any, mock_raw_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _RecordingLog()
    monkeypatch.setattr("alphaswarm.ollama_models.logger", rec)
    mock_raw_client.ps = AsyncMock(return_value=_make_ps_response(["alphaswarm-worker"]))
    await model_manager.load_model("alphaswarm-worker")
    loaded = [kw for e, kw in rec.events if e == "model_loaded"]
    assert len(loaded) == 1 and loaded[0]["load_ms"] >= 0
