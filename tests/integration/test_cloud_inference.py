"""Opt-in live smoke tests for cloud inference providers.

These tests make REAL API calls and spend a tiny amount of money.
They are SKIPPED by default (when the relevant env-var keys are absent),
so they never fail in CI.

Opt-in:
  export ALPHASWARM_TEST_ANTHROPIC_KEY="sk-ant-..."
  export ALPHASWARM_TEST_OPENAI_KEY="sk-..."
  uv run pytest tests/integration/test_cloud_inference.py -v

Network access is granted automatically because
tests/integration/conftest.py auto-applies @pytest.mark.enable_socket
to every test in this subtree.

Optional env-vars:
  ALPHASWARM_TEST_ANTHROPIC_MODEL   default: claude-3-5-haiku-latest
  ALPHASWARM_TEST_OPENAI_BASE_URL   default: https://api.openai.com/v1
  ALPHASWARM_TEST_OPENAI_MODEL      default: gpt-4o-mini
"""

from __future__ import annotations

import os

import pytest

from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.types import SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA

# ---------------------------------------------------------------------------
# Key / config resolution (module-level, at collection time)
# ---------------------------------------------------------------------------

_ANTHROPIC_KEY: str | None = os.environ.get("ALPHASWARM_TEST_ANTHROPIC_KEY")
_ANTHROPIC_MODEL: str = os.environ.get(
    "ALPHASWARM_TEST_ANTHROPIC_MODEL", "claude-3-5-haiku-latest"
)

_OPENAI_KEY: str | None = os.environ.get("ALPHASWARM_TEST_OPENAI_KEY")
_OPENAI_BASE_URL: str = os.environ.get(
    "ALPHASWARM_TEST_OPENAI_BASE_URL", "https://api.openai.com/v1"
)
_OPENAI_MODEL: str = os.environ.get("ALPHASWARM_TEST_OPENAI_MODEL", "gpt-4o-mini")

_PROMPT: list[dict[str, str]] = [
    {
        "role": "user",
        "content": "AAPL up 3% on strong iPhone demand. Quick BUY/SELL/HOLD call.",
    }
]

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ANTHROPIC_KEY,
    reason="set ALPHASWARM_TEST_ANTHROPIC_KEY to run live Anthropic smoke",
)
async def test_anthropic_provider_live_smoke() -> None:
    """Live smoke: AnthropicProvider returns a valid BUY/SELL/HOLD decision."""
    assert _ANTHROPIC_KEY is not None  # narrowed for mypy after skipif guard

    provider = AnthropicProvider(
        role=ProviderRole.WORKER,
        model=_ANTHROPIC_MODEL,
        api_key=_ANTHROPIC_KEY,
    )
    try:
        result = await provider.chat(
            _PROMPT,  # type: ignore[arg-type]
            response_schema=DECISION_JSON_SCHEMA,
            temperature=0.3,
            max_tokens=300,
        )
        decision = parse_agent_decision(result.content)
        assert decision.signal != SignalType.PARSE_ERROR, (
            f"parse_agent_decision returned PARSE_ERROR; raw content: {result.content!r}"
        )
        assert result.input_tokens is not None and result.input_tokens > 0, (
            f"input_tokens not populated: {result.input_tokens!r}"
        )
        assert result.output_tokens is not None and result.output_tokens > 0, (
            f"output_tokens not populated: {result.output_tokens!r}"
        )
    finally:
        await provider.aclose()


@pytest.mark.skipif(
    not _OPENAI_KEY,
    reason="set ALPHASWARM_TEST_OPENAI_KEY to run live OpenAI smoke",
)
async def test_openai_provider_live_smoke() -> None:
    """Live smoke: OpenAICompatProvider returns a valid BUY/SELL/HOLD decision."""
    assert _OPENAI_KEY is not None  # narrowed for mypy after skipif guard

    provider = OpenAICompatProvider(
        role=ProviderRole.WORKER,
        model=_OPENAI_MODEL,
        base_url=_OPENAI_BASE_URL,
        api_key=_OPENAI_KEY,
    )
    try:
        result = await provider.chat(
            _PROMPT,  # type: ignore[arg-type]
            response_schema=DECISION_JSON_SCHEMA,
            temperature=0.3,
            max_tokens=300,
        )
        decision = parse_agent_decision(result.content)
        assert decision.signal != SignalType.PARSE_ERROR, (
            f"parse_agent_decision returned PARSE_ERROR; raw content: {result.content!r}"
        )
        assert result.input_tokens is not None and result.input_tokens > 0, (
            f"input_tokens not populated: {result.input_tokens!r}"
        )
        assert result.output_tokens is not None and result.output_tokens > 0, (
            f"output_tokens not populated: {result.output_tokens!r}"
        )
    finally:
        await provider.aclose()
