"""chat_structured: schema-constrained decode, parse fallbacks, one validated retry.

docs/DECISIONS.md#adr-structured-output
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from alphaswarm.errors import AuthError, StructuredOutputError
from alphaswarm.inference.structured import (
    StructuredResult,
    chat_structured,
    json_object_candidates,
    parse_structured,
    strip_code_fences,
)
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

MESSAGES: list[InferenceMessage] = [
    {"role": "system", "content": "Return the reply object."},
    {"role": "user", "content": "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics."},
]


class Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    score: float = Field(ge=0.0, le=1.0)


class Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str
    items: list[Item]


class StrictReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str


GOOD = json.dumps({"headline": "Deal priced in", "items": [{"name": "ZZZT", "score": 0.7}]})


def _provider(*contents: str) -> FakeInferenceProvider:
    return FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=c, model="fake-orch") for c in contents],
    )


def test_candidates_find_the_balanced_object_inside_prose() -> None:
    text = 'Sure! {"a": "}", "b": 1} and also {"c": 2}'
    assert json_object_candidates(text)[0] == '{"a": "}", "b": 1}'
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_parse_structured_tiers() -> None:
    assert parse_structured(GOOD, Reply)[1] == 1
    assert parse_structured(f"```json\n{GOOD}\n```", Reply)[1] == 2
    assert parse_structured(f"Here you go:\n{GOOD}\nThanks.", Reply)[1] == 2
    with pytest.raises(ValueError):
        parse_structured("no json at all", Reply)


async def test_tier1_single_call_sends_portable_schema_and_options() -> None:
    provider = _provider(GOOD)
    result = await chat_structured(provider, MESSAGES, Reply, temperature=0.2, max_tokens=500)
    assert isinstance(result, StructuredResult)
    assert (result.parse_tier, result.attempts) == (1, 1)
    assert result.value.items[0].name == "ZZZT"
    call = provider.calls[0]
    assert call["temperature"] == 0.2 and call["max_tokens"] == 500
    assert call["json_mode"] is False
    schema = call["response_schema"]
    assert "$defs" not in schema
    assert "$ref" not in json.dumps(schema)
    assert schema["properties"]["items"]["items"]["properties"]["score"]["type"] == "number"


async def test_fenced_reply_is_tier2_without_a_retry() -> None:
    provider = _provider(f"```json\n{GOOD}\n```")
    result = await chat_structured(provider, MESSAGES, Reply)
    assert (result.parse_tier, result.attempts) == (2, 1)
    assert len(provider.calls) == 1


async def test_invalid_then_valid_retries_once_with_field_errors() -> None:
    bad = json.dumps({"headline": "Deal", "items": [{"name": "ZZZT", "score": "SECRET-7.5"}]})
    provider = _provider(bad, GOOD)
    result = await chat_structured(provider, MESSAGES, Reply)
    assert result.attempts == 2
    retry_messages = provider.calls[1]["messages"]
    # The retry is the original conversation plus one correction turn; the
    # rejected reply is never echoed back as an assistant turn.
    assert retry_messages[:-1] == MESSAGES
    correction = retry_messages[-1]["content"]
    assert retry_messages[-1]["role"] == "user"
    assert "did not match the required JSON schema" in correction
    assert "items.0.score" in correction


async def test_correction_never_echoes_input_values() -> None:
    bad = json.dumps({"headline": "Deal", "items": [{"name": "ZZZT", "score": "SECRET-7.5"}]})
    provider = _provider(bad, GOOD)
    await chat_structured(provider, MESSAGES, Reply)
    assert "SECRET-7.5" not in json.dumps(provider.calls[1]["messages"])


async def test_correction_masks_extra_key_names() -> None:
    bad = json.dumps({"headline": "Deal", "XQZW": 12})
    good = json.dumps({"headline": "Deal"})
    provider = _provider(bad, good)
    await chat_structured(provider, MESSAGES, StrictReply)
    retry_messages = provider.calls[1]["messages"]
    assert "<extra>" in retry_messages[-1]["content"]
    assert "XQZW" not in json.dumps(retry_messages)


async def test_two_invalid_replies_raise_tier3_error() -> None:
    provider = _provider("nope", "still nope")
    with pytest.raises(StructuredOutputError) as exc:
        await chat_structured(provider, MESSAGES, Reply)
    assert exc.value.parse_tier == 3
    assert exc.value.attempts == 2
    assert exc.value.model == "fake-orch"
    assert len(provider.calls) == 2


async def test_retries_zero_means_one_call() -> None:
    provider = _provider("nope")
    with pytest.raises(StructuredOutputError):
        await chat_structured(provider, MESSAGES, Reply, retries=0)
    assert len(provider.calls) == 1


async def test_empty_reply_retry_has_no_assistant_turn() -> None:
    provider = _provider("", GOOD)
    await chat_structured(provider, MESSAGES, Reply)
    retry_messages = provider.calls[1]["messages"]
    assert retry_messages[:-1] == MESSAGES
    assert all(message["role"] != "assistant" for message in retry_messages)
    assert "no JSON object" in retry_messages[-1]["content"]


async def test_provider_errors_propagate_unwrapped() -> None:
    def _boom(**_: object) -> InferenceResult:
        raise AuthError("bad key", provider="anthropic", model="claude-test")

    provider = FakeInferenceProvider(role=ProviderRole.ORCHESTRATOR, model="m", scripted=_boom)
    with pytest.raises(AuthError):
        await chat_structured(provider, MESSAGES, Reply)


async def test_schema_override_is_sent_instead_of_the_model_schema() -> None:
    override = Reply.model_json_schema()
    override["properties"]["headline"] = {"type": "string", "enum": ["Deal priced in"]}
    provider = _provider(GOOD)
    await chat_structured(provider, MESSAGES, Reply, schema=override)
    sent = provider.calls[0]["response_schema"]
    assert sent["properties"]["headline"]["enum"] == ["Deal priced in"]


async def test_negative_retries_rejected() -> None:
    with pytest.raises(ValueError, match="retries"):
        await chat_structured(_provider(GOOD), MESSAGES, Reply, retries=-1)
