"""Faithful provider-quirk tests for OpenAICompatProvider.

Each test exercises real wire behaviour for a specific provider using an
injected ``httpx.MockTransport`` — NO network calls are made.  The handlers
capture the actual outgoing request (URL, headers, body) so assertions are on
the concrete wire representation, not just "no error was raised".

Providers covered:
    1. OpenRouter — extra headers, json_schema response_format
    2. Google Gemini (OpenAI-compat) — trailing-slash rstrip + json_schema→json_object downgrade
    3. NVIDIA NIM (Nemotron) — normal json_schema path
    4. Factory wiring — build_providers produces BudgetTrackingProvider(OpenAICompatProvider)
    5. Presets shape — GET /api/settings returns well-formed provider_presets list
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from alphaswarm.config import InferenceConfig, ProviderType, RoleConfig
from alphaswarm.inference.budget import BudgetTrackingProvider
from alphaswarm.inference.factory import RateLimitController, build_controller, build_providers
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.worker import DECISION_JSON_SCHEMA

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

# A well-formed decision JSON the provider will return.
_DECISION_JSON = json.dumps(
    {
        "signal": "buy",
        "confidence": 0.82,
        "sentiment": 0.6,
        "rationale": "Positive momentum confirmed by multiple sources.",
        "cited_agents": ["agent-01", "agent-02"],
    }
)

_MESSAGES: list[dict[str, str]] = [{"role": "user", "content": "What is your signal?"}]

_DEFAULT_USAGE = {"prompt_tokens": 120, "completion_tokens": 45}


def _openai_200(content: str, usage: dict[str, int] = _DEFAULT_USAGE) -> httpx.Response:
    """Return a minimal valid OpenAI chat-completions 200 response."""
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }
    return httpx.Response(200, json=body)


def _make_provider(
    handler: Any,
    *,
    role: ProviderRole = ProviderRole.WORKER,
    model: str,
    base_url: str,
    api_key: str,
    extra_headers: dict[str, str] | None = None,
    max_retries: int = 1,
) -> OpenAICompatProvider:
    """Construct an OpenAICompatProvider with a MockTransport-backed client."""
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatProvider(
        role,
        model,
        base_url=base_url,
        api_key=api_key,
        extra_headers=extra_headers,
        max_retries=max_retries,
        client=client,
    )


# ---------------------------------------------------------------------------
# 1. OpenRouter — extra headers, json_schema, full assertions
# ---------------------------------------------------------------------------


class TestOpenRouter:
    """OpenRouter uses the OpenAI-compatible interface with extra routing headers."""

    @pytest.mark.asyncio
    async def test_openrouter_request_url_and_headers_and_schema(self) -> None:
        """
        Wire assertions:
        - POST URL == https://openrouter.ai/api/v1/chat/completions (no double slash)
        - Authorization header == "Bearer sk-or-test"
        - HTTP-Referer and X-Title extra headers are present
        - Request body carries response_format.type == "json_schema"
        - Result content parses to a non-PARSE_ERROR AgentDecision
        - input_tokens / output_tokens are populated
        """
        captured_requests: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_requests.append(req)
            return _openai_200(_DECISION_JSON)

        provider = _make_provider(
            handler,
            model="google/gemini-2.5-flash",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            extra_headers={
                "HTTP-Referer": "https://x",
                "X-Title": "AlphaSwarm",
            },
        )

        result = await provider.chat(
            _MESSAGES,
            response_schema=DECISION_JSON_SCHEMA,
            temperature=0.3,
        )

        assert len(captured_requests) == 1, "expected exactly one request"
        req = captured_requests[0]

        # --- URL ---
        assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions", (
            f"unexpected URL: {req.url}"
        )

        # --- Authorization ---
        assert req.headers.get("authorization") == "Bearer sk-or-test", (
            f"unexpected Authorization: {req.headers.get('authorization')}"
        )

        # --- Extra headers ---
        assert req.headers.get("http-referer") == "https://x", (
            "HTTP-Referer header missing or wrong"
        )
        assert req.headers.get("x-title") == "AlphaSwarm", (
            "X-Title header missing or wrong"
        )

        # --- Body: response_format ---
        body: dict[str, Any] = json.loads(req.content)
        rf = body.get("response_format", {})
        assert rf.get("type") == "json_schema", (
            f"expected json_schema in response_format, got: {rf}"
        )

        # --- Parsed decision ---
        decision = parse_agent_decision(result.content)
        assert decision.signal.value != "PARSE_ERROR", (
            f"parse_agent_decision returned PARSE_ERROR; content={result.content!r}"
        )

        # --- Token counts ---
        assert result.input_tokens == 120
        assert result.output_tokens == 45


# ---------------------------------------------------------------------------
# 2. Google Gemini (OpenAI-compat) — trailing slash + json_schema→json_object downgrade
# ---------------------------------------------------------------------------


class TestGeminiTrailingSlashAndDowngrade:
    """
    Real Gemini (OpenAI-compat) wire behaviour:
    - base_url has a trailing slash → rstrip must prevent double-slash in the URL
    - Gemini does NOT support response_format json_schema → 400 on first attempt
    - Adapter sets _no_strict=True and retries with json_object → succeeds
    """

    @pytest.mark.asyncio
    async def test_gemini_trailing_slash_no_double_slash_in_url(self) -> None:
        """Both request URLs must not contain '//' after the host."""
        seen_urls: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_urls.append(str(req.url))
            if len(seen_urls) == 1:
                # First call: strict json_schema → Gemini rejects it
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format.json_schema is not supported"}},
                )
            # Second call: json_object fallback → success
            return _openai_200(_DECISION_JSON)

        provider = _make_provider(
            handler,
            model="gemini-2.0-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",  # trailing slash
            api_key="goog-test-key",
        )

        _result = await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)

        # Both requests must go to the SAME canonical URL (no double slash)
        assert len(seen_urls) == 2, f"expected exactly 2 requests, got {len(seen_urls)}"

        expected_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        for url in seen_urls:
            assert url == expected_url, (
                f"URL contains double-slash or is wrong: {url!r}"
            )
            assert "//" not in url.split("://", 1)[1], (
                f"double-slash in path: {url!r}"
            )

    @pytest.mark.asyncio
    async def test_gemini_downgrade_second_request_uses_json_object(self) -> None:
        """The retry (second) request body must use response_format.type == 'json_object'."""
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            if len(captured_bodies) == 1:
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format json_schema not supported"}},
                )
            return _openai_200(_DECISION_JSON)

        provider = _make_provider(
            handler,
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key="goog-test-key",
        )

        await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)

        assert len(captured_bodies) == 2
        # First body: strict json_schema
        assert captured_bodies[0].get("response_format", {}).get("type") == "json_schema"
        # Second body (downgrade retry): json_object
        got_rf = captured_bodies[1].get("response_format", {})
        assert got_rf.get("type") == "json_object", (
            f"expected json_object on downgrade retry, got: {got_rf}"
        )

    @pytest.mark.asyncio
    async def test_gemini_downgrade_sets_no_strict_flag(self) -> None:
        """After a successful downgrade, provider._no_strict must be True."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format.json_schema not supported strict"}},
                )
            return _openai_200(_DECISION_JSON)

        provider = _make_provider(
            handler,
            model="gemini-2.0-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key="goog-test-key",
        )

        await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)

        assert provider._no_strict is True, (
            "_no_strict must be True after a successful strict-downgrade"
        )

    @pytest.mark.asyncio
    async def test_gemini_downgrade_result_parses_to_valid_decision(self) -> None:
        """The final result from the downgraded call must parse to a valid decision."""

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            rf_type = body.get("response_format", {}).get("type", "")
            if rf_type == "json_schema":
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format json_schema not supported"}},
                )
            # json_object fallback succeeds
            return _openai_200(_DECISION_JSON)

        provider = _make_provider(
            handler,
            model="gemini-2.0-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key="goog-test-key",
        )

        result = await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)

        decision = parse_agent_decision(result.content)
        assert decision.signal.value != "PARSE_ERROR", (
            f"decision should be valid after downgrade, got PARSE_ERROR; "
            f"content={result.content!r}"
        )
        assert decision.signal.value == "buy"


# ---------------------------------------------------------------------------
# 3. NVIDIA NIM (Nemotron) — normal json_schema path
# ---------------------------------------------------------------------------


class TestNvidiaNim:
    """NVIDIA NIM supports standard OpenAI-compat json_schema — no downgrade needed."""

    @pytest.mark.asyncio
    async def test_nvidia_nim_url_and_decision_and_tokens(self) -> None:
        """
        Wire assertions:
        - URL == https://integrate.api.nvidia.com/v1/chat/completions
        - response_format.type == json_schema in the request body
        - result parses to a valid decision
        - input/output tokens populated
        """
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return _openai_200(_DECISION_JSON, {"prompt_tokens": 200, "completion_tokens": 60})

        provider = _make_provider(
            handler,
            model="nvidia/llama-3.1-nemotron-70b-instruct",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="nvapi-test-key",
        )

        result = await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)

        assert len(captured) == 1
        req = captured[0]

        # --- URL ---
        assert str(req.url) == "https://integrate.api.nvidia.com/v1/chat/completions", (
            f"unexpected URL: {req.url}"
        )

        # --- Body: json_schema ---
        body: dict[str, Any] = json.loads(req.content)
        assert body.get("response_format", {}).get("type") == "json_schema", (
            f"expected json_schema, got: {body.get('response_format')}"
        )

        # --- Decision ---
        decision = parse_agent_decision(result.content)
        assert decision.signal.value != "PARSE_ERROR"

        # --- Tokens ---
        assert result.input_tokens == 200
        assert result.output_tokens == 60


# ---------------------------------------------------------------------------
# 4. Factory wiring — build_providers produces BudgetTrackingProvider(OpenAICompatProvider)
# ---------------------------------------------------------------------------


class TestFactoryWiring:
    """Verify that presets → config → build_providers → adapter is correctly wired."""

    def test_openrouter_worker_config_produces_budget_wrapped_openai_compat(self) -> None:
        """build_providers on an OpenRouter-style RoleConfig must produce
        BudgetTrackingProvider wrapping OpenAICompatProvider with matching
        base_url and model.
        """
        cfg = InferenceConfig(
            orchestrator=RoleConfig(
                provider=ProviderType.OLLAMA,
                model="alphaswarm-orchestrator",
            ),
            worker=RoleConfig(
                provider=ProviderType.OPENAI_COMPATIBLE,
                model="google/gemini-2.5-flash",
                base_url="https://openrouter.ai/api/v1",
                api_key="sk-or-x",
            ),
            spend_cap_usd=Decimal("10.00"),
        )

        built = build_providers(
            cfg,
            ollama_client=MagicMock(name="OllamaClient"),
            ollama_model_manager=MagicMock(name="OllamaModelManager"),
        )

        # Worker must be BudgetTrackingProvider
        assert isinstance(built.worker, BudgetTrackingProvider), (
            f"expected BudgetTrackingProvider, got {type(built.worker)}"
        )

        # Inner must be OpenAICompatProvider
        inner = built.worker._inner  # type: ignore[union-attr]
        assert isinstance(inner, OpenAICompatProvider), (
            f"expected OpenAICompatProvider inside, got {type(inner)}"
        )

        # base_url and model must match config (rstrip applied)
        assert inner._base_url == "https://openrouter.ai/api/v1"
        assert inner.model == "google/gemini-2.5-flash"

    def test_openrouter_worker_build_controller_returns_rate_limit_controller(self) -> None:
        """build_controller for a cloud worker must return RateLimitController."""
        cfg = InferenceConfig(
            orchestrator=RoleConfig(
                provider=ProviderType.OLLAMA,
                model="alphaswarm-orchestrator",
            ),
            worker=RoleConfig(
                provider=ProviderType.OPENAI_COMPATIBLE,
                model="google/gemini-2.5-flash",
                base_url="https://openrouter.ai/api/v1",
                api_key="sk-or-x",
            ),
        )

        ctrl = build_controller(cfg, MagicMock(name="GovernorSettings"))
        assert isinstance(ctrl, RateLimitController), (
            f"expected RateLimitController, got {type(ctrl)}"
        )


# ---------------------------------------------------------------------------
# 5. Presets shape — GET /api/settings returns provider_presets
# ---------------------------------------------------------------------------


class TestPresetsInSettingsEndpoint:
    """GET /api/settings must return a well-formed provider_presets list."""

    def test_get_settings_returns_provider_presets_list(self) -> None:
        """provider_presets is a non-empty list of dicts with required keys."""
        from collections.abc import AsyncGenerator
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from alphaswarm.web.routes.settings import router as settings_router

        @asynccontextmanager
        async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            from alphaswarm.app import create_app_state
            from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
            from alphaswarm.web.connection_manager import ConnectionManager
            from alphaswarm.web.replay_manager import ReplayManager
            from alphaswarm.web.simulation_manager import SimulationManager

            settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
            brackets = load_bracket_configs()
            personas = generate_personas(brackets)
            app_state = create_app_state(
                settings, personas, with_ollama=False, with_neo4j=False
            )
            replay_manager = ReplayManager(app_state)
            sim_manager = SimulationManager(
                app_state, brackets, replay_manager=replay_manager
            )
            app.state.app_state = app_state
            app.state.sim_manager = sim_manager
            app.state.replay_manager = replay_manager
            app.state.connection_manager = ConnectionManager()
            yield
            if app_state.graph_manager is not None:
                await app_state.graph_manager.close()

        fapp = FastAPI(lifespan=_lifespan)
        fapp.include_router(settings_router, prefix="/api")

        valid_providers = {pt.value for pt in ProviderType}

        with (
            patch(
                "alphaswarm.web.routes.settings.load_inference_config",
                return_value=InferenceConfig(
                    orchestrator=RoleConfig(
                        provider=ProviderType.OLLAMA, model="local-orch"
                    ),
                    worker=RoleConfig(
                        provider=ProviderType.OLLAMA, model="local-worker"
                    ),
                ),
            ),
            patch(
                "alphaswarm.web.routes.settings._local_model_names",
                new=AsyncMock(return_value=[]),
            ),
            TestClient(fapp) as client,
        ):
            r = client.get("/api/settings")

        assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
        data = r.json()

        assert "provider_presets" in data, "provider_presets key missing from response"
        presets = data["provider_presets"]
        assert isinstance(presets, list) and len(presets) > 0, (
            "provider_presets must be a non-empty list"
        )

        required_keys = {"label", "provider", "models"}
        for preset in presets:
            missing = required_keys - preset.keys()
            assert not missing, f"preset {preset!r} missing keys: {missing}"
            # provider must be a valid ProviderType value
            assert preset["provider"] in valid_providers, (
                f"preset provider {preset['provider']!r} is not a valid ProviderType; "
                f"valid={valid_providers}"
            )
            assert isinstance(preset["models"], list)

    def test_provider_presets_contains_openrouter(self) -> None:
        """PROVIDER_PRESETS constant must include an OpenRouter preset."""
        from alphaswarm.web.routes.settings import PROVIDER_PRESETS

        labels = [p.label for p in PROVIDER_PRESETS]
        assert "OpenRouter" in labels, f"OpenRouter preset missing; labels={labels}"

        openrouter = next(p for p in PROVIDER_PRESETS if p.label == "OpenRouter")
        assert openrouter.base_url == "https://openrouter.ai/api/v1"
        assert openrouter.provider == ProviderType.OPENAI_COMPATIBLE

    def test_provider_presets_contains_gemini(self) -> None:
        """PROVIDER_PRESETS must include a Google Gemini preset with correct base_url."""
        from alphaswarm.web.routes.settings import PROVIDER_PRESETS

        gemini = next((p for p in PROVIDER_PRESETS if p.label == "Google Gemini"), None)
        assert gemini is not None, "Google Gemini preset missing"
        assert gemini.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
        assert gemini.provider == ProviderType.OPENAI_COMPATIBLE

    def test_provider_presets_contains_nvidia(self) -> None:
        """PROVIDER_PRESETS must include an NVIDIA NIM preset."""
        from alphaswarm.web.routes.settings import PROVIDER_PRESETS

        nvidia = next((p for p in PROVIDER_PRESETS if p.label == "NVIDIA NIM"), None)
        assert nvidia is not None, "NVIDIA NIM preset missing"
        assert nvidia.base_url == "https://integrate.api.nvidia.com/v1"
        assert nvidia.provider == ProviderType.OPENAI_COMPATIBLE

    def test_all_presets_have_valid_provider_type(self) -> None:
        """Every preset in PROVIDER_PRESETS must have a valid ProviderType value."""
        from alphaswarm.web.routes.settings import PROVIDER_PRESETS

        valid = {pt.value for pt in ProviderType}
        for preset in PROVIDER_PRESETS:
            assert preset.provider in valid, (
                f"Preset {preset.label!r} has invalid provider {preset.provider!r}"
            )
