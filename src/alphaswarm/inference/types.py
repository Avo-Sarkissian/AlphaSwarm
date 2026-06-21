"""Normalized inference types shared across all provider backends.

These types form the provider-agnostic contract so callers never import
Ollama-specific structures directly.  Both the local (Ollama) and future
cloud adapters produce and consume these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict


class ProviderRole(StrEnum):
    """Distinguishes the two inference roles in AlphaSwarm.

    ORCHESTRATOR: The high-quality model responsible for synthesis, reasoning,
        and decision-making across agent rounds.
    WORKER: The fast, lower-cost model used for individual agent inference
        during simulation rounds.
    """

    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"


class InferenceMessage(TypedDict):
    """A single turn in a chat conversation.

    Mirrors the OpenAI chat-message schema so the same structure works for
    Ollama (which accepts the same shape) and future cloud adapters.

    Fields:
        role: One of "system", "user", or "assistant".
        content: The text content of the message.
    """

    role: str
    content: str


@dataclass(frozen=True)
class InferenceResult:
    """Normalized output from any inference provider.

    Attributes:
        content: The generated text (raw or JSON string).
        model: The model identifier that produced the response.
        input_tokens: Number of prompt tokens consumed (None if provider
            does not report this).
        output_tokens: Number of completion tokens generated (None if
            provider does not report this).
        eval_count: Ollama-specific completion token count alias (None for
            non-Ollama providers).
        eval_duration_ns: Ollama-specific wall-clock duration in nanoseconds
            (None for non-Ollama providers).
    """

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    eval_count: int | None = None
    eval_duration_ns: int | None = None
