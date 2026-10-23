"""AlphaSwarm inference abstraction (docs/DECISIONS.md#adr-local-first-inference).

Importing the package loads only the provider-agnostic types and the
InferenceProvider protocol. Every other public name (adapters, budget, factory,
rate limiting, schema helpers) is imported on first attribute access (PEP 562),
so `import alphaswarm.inference.types` does not load the anthropic SDK, httpx or
ollama. New code should import from the submodule that defines a name.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final

from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

if TYPE_CHECKING:
    from alphaswarm.inference.anthropic_provider import AnthropicProvider
    from alphaswarm.inference.budget import (
        DEFAULT_PRICING,
        BudgetMeter,
        BudgetTrackingProvider,
        RunEstimate,
        estimate_run,
    )
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.factory import (
        BuiltProviders,
        build_controller,
        build_providers,
        inference_mode,
    )
    from alphaswarm.inference.openai_provider import OpenAICompatProvider
    from alphaswarm.inference.rate_limit import RateLimitController, TokenBucket
    from alphaswarm.inference.schema import (
        extract_anthropic_tool_json,
        to_anthropic_tool,
        to_openai_json_object,
        to_openai_response_format,
    )

_LAZY_EXPORTS: Final[dict[str, str]] = {
    "AnthropicProvider": "alphaswarm.inference.anthropic_provider",
    "BudgetMeter": "alphaswarm.inference.budget",
    "BudgetTrackingProvider": "alphaswarm.inference.budget",
    "BuiltProviders": "alphaswarm.inference.factory",
    "ConcurrencyController": "alphaswarm.inference.concurrency",
    "DEFAULT_PRICING": "alphaswarm.inference.budget",
    "OpenAICompatProvider": "alphaswarm.inference.openai_provider",
    "RateLimitController": "alphaswarm.inference.rate_limit",
    "RunEstimate": "alphaswarm.inference.budget",
    "TokenBucket": "alphaswarm.inference.rate_limit",
    "build_controller": "alphaswarm.inference.factory",
    "build_providers": "alphaswarm.inference.factory",
    "estimate_run": "alphaswarm.inference.budget",
    "extract_anthropic_tool_json": "alphaswarm.inference.schema",
    "inference_mode": "alphaswarm.inference.factory",
    "to_anthropic_tool": "alphaswarm.inference.schema",
    "to_openai_json_object": "alphaswarm.inference.schema",
    "to_openai_response_format": "alphaswarm.inference.schema",
}

__all__ = [
    "AnthropicProvider",
    "BudgetMeter",
    "BudgetTrackingProvider",
    "BuiltProviders",
    "ConcurrencyController",
    "DEFAULT_PRICING",
    "InferenceMessage",
    "InferenceProvider",
    "InferenceResult",
    "OpenAICompatProvider",
    "ProviderRole",
    "RateLimitController",
    "RunEstimate",
    "TokenBucket",
    "build_controller",
    "build_providers",
    "estimate_run",
    "extract_anthropic_tool_json",
    "inference_mode",
    "to_anthropic_tool",
    "to_openai_json_object",
    "to_openai_response_format",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache so later lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
