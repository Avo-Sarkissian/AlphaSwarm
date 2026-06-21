"""AlphaSwarm inference abstraction package.

Provides a provider-agnostic interface for LLM inference, supporting local
Ollama inference alongside optional cloud backends (OpenAI-compatible and
Anthropic).  The local path is unchanged; cloud adapters are additive.

Public surface:
    ProviderRole       — ORCHESTRATOR | WORKER enum
    InferenceMessage   — TypedDict for chat turn (role + content)
    InferenceResult    — Frozen dataclass for normalized provider output
    InferenceProvider  — Protocol every backend must satisfy

    Schema translation helpers (cloud providers):
    to_openai_response_format   — wrap schema for OpenAI strict JSON mode
    to_openai_json_object       — unconstrained OpenAI JSON mode dict
    to_anthropic_tool           — wrap schema as Anthropic tool definition
    extract_anthropic_tool_json — pull JSON payload from Anthropic tool-use blocks
"""

from __future__ import annotations

from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.schema import (
    extract_anthropic_tool_json,
    to_anthropic_tool,
    to_openai_json_object,
    to_openai_response_format,
)
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

__all__ = [
    "InferenceMessage",
    "InferenceProvider",
    "InferenceResult",
    "OpenAICompatProvider",
    "ProviderRole",
    "extract_anthropic_tool_json",
    "to_anthropic_tool",
    "to_openai_json_object",
    "to_openai_response_format",
]
