"""AlphaSwarm inference abstraction package.

Provides a provider-agnostic interface for LLM inference, supporting local
Ollama inference alongside optional cloud backends (OpenAI-compatible and
Anthropic).  The local path is unchanged; cloud adapters are additive.

Public surface:
    ProviderRole       — ORCHESTRATOR | WORKER enum
    InferenceMessage   — TypedDict for chat turn (role + content)
    InferenceResult    — Frozen dataclass for normalized provider output
    InferenceProvider  — Protocol every backend must satisfy
"""

from __future__ import annotations

from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

__all__ = [
    "InferenceMessage",
    "InferenceResult",
    "ProviderRole",
]
