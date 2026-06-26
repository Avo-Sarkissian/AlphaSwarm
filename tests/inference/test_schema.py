"""Tests for inference schema translation helpers.

TDD: tests written before implementation. Tests cover:
- to_openai_response_format: outer shape, strict normalization, no mutation
- to_openai_json_object: exact dict
- to_anthropic_tool: name/description/input_schema passthrough
- extract_anthropic_tool_json: dict blocks, object blocks, name filtering, ValueError
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

# These imports will fail until schema.py is implemented (RED phase)
from alphaswarm.inference.schema import (
    extract_anthropic_tool_json,
    to_anthropic_tool,
    to_openai_json_object,
    to_openai_response_format,
)

# Import the real DECISION_JSON_SCHEMA for realistic tests
from alphaswarm.worker import DECISION_JSON_SCHEMA

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TINY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "number"},
    },
}

NESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "value": {"type": "integer"},
            },
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "val": {"type": "string"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# to_openai_response_format
# ---------------------------------------------------------------------------


class TestToOpenaiResponseFormat:
    def test_outer_wrapper_shape(self) -> None:
        result = to_openai_response_format(TINY_SCHEMA)
        assert result["type"] == "json_schema"
        assert "json_schema" in result
        js = result["json_schema"]
        assert js["name"] == "decision"  # default name
        assert js["strict"] is True
        assert "schema" in js

    def test_custom_name(self) -> None:
        result = to_openai_response_format(TINY_SCHEMA, name="my_schema")
        assert result["json_schema"]["name"] == "my_schema"

    def test_top_level_object_gets_additional_properties_false(self) -> None:
        result = to_openai_response_format(TINY_SCHEMA)
        schema = result["json_schema"]["schema"]
        assert schema["additionalProperties"] is False

    def test_top_level_object_gets_required_all_keys(self) -> None:
        result = to_openai_response_format(TINY_SCHEMA)
        schema = result["json_schema"]["schema"]
        assert set(schema["required"]) == {"name", "score"}

    def test_input_not_mutated(self) -> None:
        original = copy.deepcopy(TINY_SCHEMA)
        to_openai_response_format(TINY_SCHEMA)
        assert original == TINY_SCHEMA

    def test_nested_object_normalized(self) -> None:
        result = to_openai_response_format(NESTED_SCHEMA)
        schema = result["json_schema"]["schema"]
        meta = schema["properties"]["meta"]
        assert meta["additionalProperties"] is False
        assert set(meta["required"]) == {"label", "value"}

    def test_array_items_object_normalized(self) -> None:
        result = to_openai_response_format(NESTED_SCHEMA)
        schema = result["json_schema"]["schema"]
        items = schema["properties"]["tags"]["items"]
        assert items["additionalProperties"] is False
        assert set(items["required"]) == {"key", "val"}

    def test_nested_input_not_mutated(self) -> None:
        original = copy.deepcopy(NESTED_SCHEMA)
        to_openai_response_format(NESTED_SCHEMA)
        assert original == NESTED_SCHEMA

    # --- realistic schema ---

    def test_decision_schema_outer_shape(self) -> None:
        result = to_openai_response_format(DECISION_JSON_SCHEMA)
        assert result["type"] == "json_schema"
        assert result["json_schema"]["strict"] is True

    def test_decision_schema_additionalproperties(self) -> None:
        result = to_openai_response_format(DECISION_JSON_SCHEMA)
        schema = result["json_schema"]["schema"]
        assert schema["additionalProperties"] is False

    def test_decision_schema_required_all_keys(self) -> None:
        result = to_openai_response_format(DECISION_JSON_SCHEMA)
        schema = result["json_schema"]["schema"]
        expected = {"signal", "confidence", "sentiment", "rationale", "cited_agents"}
        assert set(schema["required"]) == expected

    def test_decision_schema_array_items_not_object_unchanged(self) -> None:
        """cited_agents items are plain strings — no normalization applied."""
        result = to_openai_response_format(DECISION_JSON_SCHEMA)
        schema = result["json_schema"]["schema"]
        items = schema["properties"]["cited_agents"]["items"]
        # items is {"type": "string"} — no additionalProperties injected
        assert "additionalProperties" not in items

    def test_decision_schema_input_not_mutated(self) -> None:
        original = copy.deepcopy(DECISION_JSON_SCHEMA)
        to_openai_response_format(DECISION_JSON_SCHEMA)
        assert original == DECISION_JSON_SCHEMA

    def test_decision_schema_strips_strict_forbidden_keywords(self) -> None:
        """F-10: OpenAI strict mode 400s on minimum/maximum/etc. They must be
        stripped from every node while strict/additionalProperties/required remain,
        else the first call permanently downgrades the run to json_object mode."""
        result = to_openai_response_format(DECISION_JSON_SCHEMA)
        forbidden = {
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
            "multipleOf", "minLength", "maxLength", "pattern", "format",
            "default", "minItems", "maxItems", "uniqueItems",
        }

        def _assert_clean(node: object) -> None:
            if isinstance(node, dict):
                assert forbidden.isdisjoint(node.keys()), f"forbidden key in {node!r}"
                for v in node.values():
                    _assert_clean(v)
            elif isinstance(node, list):
                for v in node:
                    _assert_clean(v)

        _assert_clean(result["json_schema"]["schema"])
        # strict-mode markers survive the strip
        assert result["json_schema"]["strict"] is True
        assert result["json_schema"]["schema"]["additionalProperties"] is False
        assert "confidence" in result["json_schema"]["schema"]["required"]

    def test_existing_required_preserved_when_complete(self) -> None:
        """If schema already has required covering all keys it should not duplicate."""
        schema_with_required: dict[str, Any] = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        }
        result = to_openai_response_format(schema_with_required)
        norm = result["json_schema"]["schema"]
        assert set(norm["required"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# to_openai_json_object
# ---------------------------------------------------------------------------


class TestToOpenaiJsonObject:
    def test_exact_dict(self) -> None:
        assert to_openai_json_object() == {"type": "json_object"}


# ---------------------------------------------------------------------------
# to_anthropic_tool
# ---------------------------------------------------------------------------


class TestToAnthropicTool:
    def test_default_name_and_description(self) -> None:
        result = to_anthropic_tool(TINY_SCHEMA)
        assert result["name"] == "emit_decision"
        assert result["description"] == "Return the structured decision."

    def test_custom_name_and_description(self) -> None:
        result = to_anthropic_tool(TINY_SCHEMA, name="my_tool", description="Does X.")
        assert result["name"] == "my_tool"
        assert result["description"] == "Does X."

    def test_input_schema_is_passthrough(self) -> None:
        result = to_anthropic_tool(DECISION_JSON_SCHEMA)
        # input_schema should be the schema object unchanged (no normalization)
        assert result["input_schema"] is DECISION_JSON_SCHEMA

    def test_no_additional_properties_injected(self) -> None:
        result = to_anthropic_tool(TINY_SCHEMA)
        # Anthropic doesn't need strict normalization — additionalProperties NOT added
        assert "additionalProperties" not in result["input_schema"]

    def test_keys_present(self) -> None:
        result = to_anthropic_tool(TINY_SCHEMA)
        assert set(result.keys()) == {"name", "description", "input_schema"}


# ---------------------------------------------------------------------------
# extract_anthropic_tool_json
# ---------------------------------------------------------------------------


class _FakeToolUseBlock:
    """Minimal SDK-style object with .type / .name / .input attributes."""

    def __init__(self, type_: str, name: str, input_: dict[str, Any]) -> None:
        self.type = type_
        self.name = name
        self.input = input_


class _FakeTextBlock:
    type = "text"
    text = "some text"


class TestExtractAnthropicToolJson:
    def _dict_block(
        self, type_: str, name: str, input_: dict[str, Any]
    ) -> dict[str, Any]:
        return {"type": type_, "name": name, "input": input_}

    # --- dict blocks ---

    def test_dict_block_returns_json_string(self) -> None:
        payload = {"signal": "buy", "confidence": 0.9}
        blocks = [self._dict_block("tool_use", "emit_decision", payload)]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_dict_block_custom_name(self) -> None:
        payload = {"x": 1}
        blocks = [self._dict_block("tool_use", "my_tool", payload)]
        result = extract_anthropic_tool_json(blocks, name="my_tool")
        assert json.loads(result) == payload

    def test_dict_block_ignores_text_blocks(self) -> None:
        payload = {"signal": "hold"}
        blocks: list[Any] = [
            {"type": "text", "text": "hello"},
            self._dict_block("tool_use", "emit_decision", payload),
        ]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_dict_block_ignores_wrong_tool_name(self) -> None:
        payload = {"signal": "sell"}
        blocks: list[Any] = [
            self._dict_block("tool_use", "other_tool", {"x": 0}),
            self._dict_block("tool_use", "emit_decision", payload),
        ]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_dict_block_raises_when_absent(self) -> None:
        blocks: list[Any] = [{"type": "text", "text": "nothing here"}]
        with pytest.raises(ValueError, match="emit_decision"):
            extract_anthropic_tool_json(blocks)

    # --- SDK object blocks ---

    def test_object_block_returns_json_string(self) -> None:
        payload = {"signal": "sell", "confidence": 0.5}
        blocks: list[Any] = [_FakeToolUseBlock("tool_use", "emit_decision", payload)]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_object_block_ignores_text_block(self) -> None:
        payload = {"signal": "buy"}
        blocks: list[Any] = [
            _FakeTextBlock(),
            _FakeToolUseBlock("tool_use", "emit_decision", payload),
        ]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_object_block_raises_when_absent(self) -> None:
        blocks: list[Any] = [_FakeTextBlock()]
        with pytest.raises(ValueError, match="emit_decision"):
            extract_anthropic_tool_json(blocks)

    # --- mixed dict + object ---

    def test_mixed_blocks_finds_correct_tool(self) -> None:
        payload = {"answer": 42}
        blocks: list[Any] = [
            {"type": "text", "text": "preamble"},
            _FakeTextBlock(),
            _FakeToolUseBlock("tool_use", "emit_decision", payload),
        ]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == payload

    def test_returns_first_matching_block(self) -> None:
        first_payload = {"signal": "buy"}
        second_payload = {"signal": "sell"}
        blocks: list[Any] = [
            self._dict_block("tool_use", "emit_decision", first_payload),
            self._dict_block("tool_use", "emit_decision", second_payload),
        ]
        result = extract_anthropic_tool_json(blocks)
        assert json.loads(result) == first_payload
