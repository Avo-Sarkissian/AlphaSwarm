"""Schema translation helpers for cloud provider structured-output mechanisms.

Pure functions — no I/O, no async, no side effects.  Each function accepts or
returns plain Python dicts (JSON-serialisable).  Input dicts are never mutated.

Consumers:
    OpenAI adapter  — to_openai_response_format / to_openai_json_object
    Anthropic adapter — to_anthropic_tool / extract_anthropic_tool_json
"""

from __future__ import annotations

import copy
import json
from typing import Any


# ---------------------------------------------------------------------------
# Internal normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_object(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively apply OpenAI strict-structured-outputs rules to *schema*.

    Rules applied to every node whose ``"type"`` is ``"object"``:
    - ``"additionalProperties"`` is set to ``False``.
    - ``"required"`` is set to the list of all ``properties`` keys (preserving
      insertion order so the output is deterministic).

    The function recurses into:
    - every value inside ``"properties"``
    - the ``"items"`` sub-schema of ``"array"`` nodes

    The input dict is already a deep-copy by the time this function is called,
    so mutations here are safe.
    """
    node_type = schema.get("type")

    if node_type == "object":
        props: dict[str, Any] = schema.get("properties", {})
        # Enforce strict rules
        schema["additionalProperties"] = False
        schema["required"] = list(props.keys())
        # Recurse into each property value
        for key, prop_schema in props.items():
            if isinstance(prop_schema, dict):
                props[key] = _normalise_object(prop_schema)

    elif node_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            schema["items"] = _normalise_object(items)

    return schema


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_openai_response_format(
    schema: dict[str, Any],
    *,
    name: str = "decision",
) -> dict[str, Any]:
    """Wrap *schema* in the OpenAI ``response_format`` object for strict JSON.

    The returned dict has the shape::

        {
            "type": "json_schema",
            "json_schema": {
                "name": <name>,
                "schema": <normalised>,
                "strict": True,
            },
        }

    Normalisation rules applied recursively to every ``"object"`` node:
    - ``"additionalProperties": false``
    - ``"required"`` lists **all** property keys

    The *schema* argument is deep-copied; the original is never mutated.

    Args:
        schema: Provider-agnostic JSON Schema dict (e.g. DECISION_JSON_SCHEMA).
        name:   Value for the ``json_schema.name`` field (default ``"decision"``).

    Returns:
        A dict ready to pass as ``response_format=`` to the OpenAI client.
    """
    normalised = _normalise_object(copy.deepcopy(schema))
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": normalised,
            "strict": True,
        },
    }


def to_openai_json_object() -> dict[str, Any]:
    """Return the OpenAI ``response_format`` dict for unconstrained JSON mode.

    Use this when you want the model to emit valid JSON but don't need schema
    enforcement (e.g. fallback path, or models that don't support strict mode).

    Returns:
        ``{"type": "json_object"}``
    """
    return {"type": "json_object"}


def to_anthropic_tool(
    schema: dict[str, Any],
    *,
    name: str = "emit_decision",
    description: str = "Return the structured decision.",
) -> dict[str, Any]:
    """Wrap *schema* in an Anthropic tool definition dict.

    Anthropic's tool-use API does not require ``additionalProperties`` or a
    fully-populated ``required`` array, so the schema is passed through as-is
    (no normalisation applied, no copy made).

    The returned dict has the shape::

        {
            "name": <name>,
            "description": <description>,
            "input_schema": <schema>,
        }

    Args:
        schema:      Provider-agnostic JSON Schema dict.
        name:        Tool name (default ``"emit_decision"``).
        description: Human-readable description surfaced to the model.

    Returns:
        A dict ready to include in the ``tools=`` list passed to the Anthropic
        client.
    """
    return {
        "name": name,
        "description": description,
        "input_schema": schema,
    }


def extract_anthropic_tool_json(
    content_blocks: list[Any],
    *,
    name: str = "emit_decision",
) -> str:
    """Extract the JSON payload from an Anthropic tool-use content block.

    Searches *content_blocks* for the first block whose type is ``"tool_use"``
    and whose name matches *name*, then returns ``json.dumps(block.input)``.

    Supports **both** SDK object blocks (attributes ``.type``, ``.name``,
    ``.input``) and plain-dict blocks (keys ``"type"``, ``"name"``,
    ``"input"``), so unit tests can pass lightweight dicts without importing
    the Anthropic SDK.

    Args:
        content_blocks: The ``message.content`` list returned by the Anthropic
            client (may contain text blocks, tool-use blocks, etc.).
        name:           The tool name to match (default ``"emit_decision"``).

    Returns:
        A JSON string (``str``) of the matched block's ``input`` dict.

    Raises:
        ValueError: If no ``tool_use`` block with the given *name* is found.
    """
    for block in content_blocks:
        # --- dict-style block ---
        if isinstance(block, dict):
            if block.get("type") == "tool_use" and block.get("name") == name:
                return json.dumps(block["input"])
        # --- SDK object-style block ---
        else:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type == "tool_use" and block_name == name:
                return json.dumps(block.input)

    raise ValueError(
        f"No tool_use block with name={name!r} found in content_blocks. "
        f"Got block types: {[_block_type(b) for b in content_blocks]}"
    )


def _block_type(block: Any) -> str:
    """Return the type string of *block* for error messages."""
    if isinstance(block, dict):
        return str(block.get("type", "<unknown>"))
    return str(getattr(block, "type", "<unknown>"))
