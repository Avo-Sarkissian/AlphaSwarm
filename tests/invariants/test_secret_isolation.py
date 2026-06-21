"""Secret-leak invariant: sentinel API key must never appear in logs or API responses.

Why Neo4j and WebSocket surfaces are N/A for API keys (contrast with the holdings
canary which DOES traverse Neo4j/WS):
  - API keys live only in the gitignored .secrets file and the in-process
    InferenceConfig object.  They are never serialised into simulation cycles,
    Neo4j graph properties, or WS broadcast frames.
  - Holdings data flows through synthesize() → Neo4j read → WS publish path;
    inference credentials do not follow that path at all.
  - Therefore only two surfaces need to be tested: structured logs and the
    GET /api/settings HTTP response (the only surface that serialises
    InferenceConfig to the network).

Surfaces tested:
  Surface #1 (logs)       — structlog JSON output run through pii_redaction_processor.
  Surface #2 (GET /settings) — FastAPI TestClient; sentinel key must be absent
                               from the JSON response body.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import structlog

from alphaswarm.config import InferenceConfig, ProviderType, RoleConfig
from alphaswarm.logging import _redact_mapping

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

SNTL_API_KEY_DONOTLOG_0000 = "SNTL_API_KEY_DONOTLOG_0000"

# ---------------------------------------------------------------------------
# Shared test-app factory (mirrors test_web_settings.py pattern)
# ---------------------------------------------------------------------------


def _make_settings_test_app() -> Any:
    """Build an isolated FastAPI test app with the settings router registered."""
    from fastapi import FastAPI

    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.settings import router as settings_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        replay_manager = ReplayManager(app_state)
        sim_manager = SimulationManager(app_state, brackets, replay_manager=replay_manager)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    fapp = FastAPI(title="AlphaSwarm-SecretIsolation-Test", lifespan=_lifespan)
    fapp.include_router(settings_router, prefix="/api")
    return fapp


def _mock_load_cfg(cfg: InferenceConfig) -> Any:
    return patch(
        "alphaswarm.web.routes.settings.load_inference_config",
        return_value=cfg,
    )


def _mock_ollama_list(models: list[str] | None = None) -> Any:
    return patch(
        "alphaswarm.web.routes.settings._local_model_names",
        new=AsyncMock(return_value=models or []),
    )


# ---------------------------------------------------------------------------
# Surface #1 — Logs
# ---------------------------------------------------------------------------


@pytest.fixture()
def _capture_buf() -> io.StringIO:
    """StringIO buffer wired as the structlog sink (mirrors conftest.capture_logs)."""
    buf = io.StringIO()

    class _BufLogger:
        def msg(self, message: str) -> None:
            buf.write(message + "\n")

        def debug(self, message: str) -> None:
            self.msg(message)

        def info(self, message: str) -> None:
            self.msg(message)

        def warning(self, message: str) -> None:
            self.msg(message)

        def error(self, message: str) -> None:
            self.msg(message)

        def critical(self, message: str) -> None:
            self.msg(message)

    def _factory(*args: Any, **kwargs: Any) -> _BufLogger:
        return _BufLogger()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            _redact_mapping_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG
        context_class=dict,
        logger_factory=_factory,  # type: ignore[arg-type]
        cache_logger_on_first_use=False,
    )
    return buf


def _redact_mapping_processor(
    logger: Any, method_name: str, event_dict: Any
) -> Any:
    """Thin shim: calls _redact_mapping directly so we can unit-test it."""
    return _redact_mapping(dict(event_dict), depth=0, seen=set())


def test_top_level_api_key_redacted_in_logs() -> None:
    """A top-level api_key field containing the sentinel is redacted to [REDACTED]."""
    event: dict[str, Any] = {"api_key": SNTL_API_KEY_DONOTLOG_0000, "event": "login"}
    result = _redact_mapping(event, depth=0, seen=set())
    result_str = json.dumps(result)

    assert SNTL_API_KEY_DONOTLOG_0000 not in result_str, (
        f"Sentinel leaked at top level. Result: {result_str}"
    )
    assert "[REDACTED]" in result_str, "Expected [REDACTED] in result"


def test_nested_role_api_key_redacted_in_logs() -> None:
    """A nested role config api_key containing the sentinel is also redacted."""
    event: dict[str, Any] = {
        "event": "config_loaded",
        "config": {
            "orchestrator": {
                "api_key": SNTL_API_KEY_DONOTLOG_0000,
                "model": "gpt-4o",
            }
        },
    }
    result = _redact_mapping(event, depth=0, seen=set())
    result_str = json.dumps(result)

    assert SNTL_API_KEY_DONOTLOG_0000 not in result_str, (
        f"Sentinel leaked in nested config. Result: {result_str}"
    )
    assert "[REDACTED]" in result_str, "Expected [REDACTED] in result"


def test_authorization_header_redacted_in_logs() -> None:
    """An Authorization header value is redacted."""
    event: dict[str, Any] = {
        "event": "outbound_request",
        "Authorization": f"Bearer {SNTL_API_KEY_DONOTLOG_0000}",
    }
    result = _redact_mapping(event, depth=0, seen=set())
    result_str = json.dumps(result)

    assert SNTL_API_KEY_DONOTLOG_0000 not in result_str, (
        f"Sentinel leaked in Authorization header. Result: {result_str}"
    )
    assert "[REDACTED]" in result_str


def test_bearer_token_key_redacted_in_logs() -> None:
    """A bearer_token field is redacted."""
    event: dict[str, Any] = {
        "event": "auth",
        "bearer_token": SNTL_API_KEY_DONOTLOG_0000,
    }
    result = _redact_mapping(event, depth=0, seen=set())
    result_str = json.dumps(result)

    assert SNTL_API_KEY_DONOTLOG_0000 not in result_str
    assert "[REDACTED]" in result_str


# ---------------------------------------------------------------------------
# Surface #2 — GET /api/settings response
# ---------------------------------------------------------------------------


_SENTINEL_INFERENCE_CFG = InferenceConfig(
    orchestrator=RoleConfig(
        provider=ProviderType.ANTHROPIC,
        model="claude-3-5-haiku-20241022",
        api_key=SNTL_API_KEY_DONOTLOG_0000,
    ),
    worker=RoleConfig(
        provider=ProviderType.ANTHROPIC,
        model="claude-3-5-haiku-20241022",
        api_key=SNTL_API_KEY_DONOTLOG_0000,
    ),
)


def test_sentinel_absent_from_get_settings_response() -> None:
    """GET /api/settings must NOT expose the raw sentinel API key."""
    from fastapi.testclient import TestClient

    with _mock_load_cfg(_SENTINEL_INFERENCE_CFG), _mock_ollama_list():
        with TestClient(_make_settings_test_app()) as client:
            r = client.get("/api/settings")

    assert r.status_code == 200
    raw = json.dumps(r.json())
    assert SNTL_API_KEY_DONOTLOG_0000 not in raw, (
        f"Sentinel API key leaked into GET /api/settings response:\n{raw}"
    )

    # Mask shape is present
    orch_key = r.json()["config"]["orchestrator"]["api_key"]
    assert orch_key["set"] is True
    assert orch_key.get("last4") is not None


# ---------------------------------------------------------------------------
# Surface #3 — Round-trip safety: masked_config never leaks sentinel
# ---------------------------------------------------------------------------


def test_masked_config_contains_no_sentinel() -> None:
    """masked_config() of a sentinel-keyed InferenceConfig contains no sentinel substring.

    Defense-in-depth: already covered by test_inference_config.py unit tests,
    but asserted here as the invariant for this surface.
    """
    from alphaswarm.config import masked_config

    result = masked_config(_SENTINEL_INFERENCE_CFG)
    serialized = json.dumps(result)

    assert SNTL_API_KEY_DONOTLOG_0000 not in serialized, (
        f"Sentinel leaked through masked_config:\n{serialized}"
    )
    assert result["orchestrator"]["api_key"]["set"] is True
    assert result["worker"]["api_key"]["set"] is True
