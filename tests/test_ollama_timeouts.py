"""Per-role Ollama HTTP timeouts (docs/DECISIONS.md#adr-inference-timeouts)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from alphaswarm.app import create_app_state
from alphaswarm.errors import OllamaInferenceError
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ollama_client import OllamaClient, OllamaTimeouts
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.settings import AppSettings, OllamaSettings

MESSAGES = [{"role": "user", "content": "ZZZT Holdings"}]


def test_settings_defaults() -> None:
    s = OllamaSettings()
    assert (s.connect_timeout_s, s.worker_read_timeout_s, s.orchestrator_read_timeout_s) == (
        5.0,
        120.0,
        600.0,
    )
    assert "request_timeout_seconds" not in OllamaSettings.model_fields


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASWARM_OLLAMA__CONNECT_TIMEOUT_S", "2.5")
    monkeypatch.setenv("ALPHASWARM_OLLAMA__WORKER_READ_TIMEOUT_S", "90")
    s = AppSettings(_env_file=None).ollama
    assert (s.connect_timeout_s, s.worker_read_timeout_s, s.orchestrator_read_timeout_s) == (
        2.5,
        90.0,
        600.0,
    )


def test_legacy_env_key_maps_to_the_orchestrator_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHASWARM_OLLAMA__REQUEST_TIMEOUT_SECONDS", "900")
    with pytest.warns(FutureWarning, match="ORCHESTRATOR_READ_TIMEOUT_S"):
        s = AppSettings(_env_file=None).ollama
    assert (s.orchestrator_read_timeout_s, s.worker_read_timeout_s) == (900.0, 120.0)


def test_explicit_value_wins_over_the_legacy_key() -> None:
    with pytest.warns(FutureWarning):
        s = OllamaSettings(request_timeout_seconds=900, orchestrator_read_timeout_s=300)
    assert s.orchestrator_read_timeout_s == 300.0


def test_httpx_timeout_per_role() -> None:
    t = OllamaTimeouts()
    assert t.httpx_timeout("worker") == httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=30.0)
    assert t.httpx_timeout("orchestrator") == httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=30.0)


def test_client_builds_one_pool_per_role() -> None:
    client = OllamaClient(timeouts=OllamaTimeouts(connect_s=2.0, worker_read_s=60.0, orchestrator_read_s=300.0))
    assert client._worker_client._client.timeout == httpx.Timeout(connect=2.0, read=60.0, write=30.0, pool=30.0)
    assert client.raw_client._client.timeout == httpx.Timeout(connect=2.0, read=300.0, write=30.0, pool=30.0)


def _mock_pools(client: OllamaClient) -> tuple[AsyncMock, AsyncMock]:
    orchestrator, worker = AsyncMock(), AsyncMock()
    for pool in (orchestrator, worker):
        pool.chat.return_value = SimpleNamespace(message=SimpleNamespace(content="{}"))
    client._client = orchestrator  # type: ignore[assignment]
    client._worker_client = worker  # type: ignore[assignment]
    return orchestrator, worker


async def test_chat_routes_by_timeout_role() -> None:
    client = OllamaClient()
    orchestrator, worker = _mock_pools(client)
    await client.chat(model="alphaswarm-worker", messages=MESSAGES, timeout_role="worker")
    await client.chat(model="alphaswarm-orchestrator", messages=MESSAGES)
    assert (worker.chat.await_count, orchestrator.chat.await_count) == (1, 1)
    assert "timeout_role" not in worker.chat.await_args.kwargs


async def test_connect_timeout_fails_fast_without_retry() -> None:
    client = OllamaClient()
    _, worker = _mock_pools(client)
    worker.chat.side_effect = httpx.ConnectTimeout("connect timed out")
    with pytest.raises(OllamaInferenceError, match="timed out"):
        await client.chat(model="alphaswarm-worker", messages=MESSAGES, timeout_role="worker")
    assert worker.chat.await_count == 1


async def test_aclose_closes_both_pools() -> None:
    client = OllamaClient()
    await client.aclose()
    assert client.raw_client._client.is_closed
    assert client._worker_client._client.is_closed
    await client.aclose()  # idempotent


class _RecordingClient:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def chat(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(message=SimpleNamespace(content="{}"))


@pytest.mark.parametrize(
    ("role", "expected"),
    [(ProviderRole.WORKER, "worker"), (ProviderRole.ORCHESTRATOR, "orchestrator")],
)
async def test_ollama_provider_sends_its_role(role: ProviderRole, expected: str) -> None:
    fake = _RecordingClient()
    provider = OllamaProvider(role, "alphaswarm-worker", fake)  # type: ignore[arg-type]
    await provider.chat([{"role": "user", "content": "ZZZT"}])
    assert fake.kwargs["timeout_role"] == expected


def test_app_state_builds_the_client_from_settings() -> None:
    # create_app_state does not configure logging (open_runtime does), so building
    # it here has no global side effect.
    settings = AppSettings(
        _env_file=None,
        ollama=OllamaSettings(worker_read_timeout_s=90.0, orchestrator_read_timeout_s=900.0),
    )
    app_state = create_app_state(settings, generate_personas(DEFAULT_BRACKETS), with_ollama=True)
    client = app_state.ollama_client
    assert client is not None
    assert client._worker_client._client.timeout.read == 90.0
    assert client.raw_client._client.timeout.read == 900.0
