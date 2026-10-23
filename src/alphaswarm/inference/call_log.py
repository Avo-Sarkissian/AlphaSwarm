"""One structured ``inference_call`` log line per provider call.

Run context (``cycle_id``, ``round``, ``agent_id``) comes from structlog
contextvars bound by the engine; this module adds only per-call numbers.
Prompt and reply text are never logged here, which also keeps advisory
calls free of holdings (docs/DECISIONS.md#adr-inference-telemetry).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Final

import structlog

if TYPE_CHECKING:
    from alphaswarm.inference.types import InferenceResult, ProviderRole

log = structlog.get_logger(component="inference")

INFERENCE_CALL_EVENT: Final = "inference_call"


def _round_ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def emit_inference_call(result: InferenceResult, *, role: ProviderRole, latency_ms: float) -> None:
    """Log one finished call: token counts, timings, finish reason and latency."""
    log.info(
        INFERENCE_CALL_EVENT,
        role=role.value,
        model=result.model,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
        cached_prompt_tokens=result.cached_prompt_tokens,
        prefill_ms=_round_ms(result.prefill_ms),
        decode_ms=_round_ms(result.decode_ms),
        load_ms=_round_ms(result.load_ms),
        finish_reason=result.finish_reason,
        latency_ms=round(latency_ms, 1),
    )


async def logged_call(role: ProviderRole, model: str, call: Awaitable[InferenceResult]) -> InferenceResult:
    """Await one provider call and log it.

    A failure logs ``finish_reason="error"`` with the exception class (never its
    message, which can echo prompt text) and re-raises. Cancellation is not a
    call outcome and logs nothing.
    """
    started = time.perf_counter()
    try:
        result = await call
    except Exception as exc:
        log.info(
            INFERENCE_CALL_EVENT,
            role=role.value,
            model=model,
            finish_reason="error",
            error_type=type(exc).__name__,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    emit_inference_call(result, role=role, latency_ms=(time.perf_counter() - started) * 1000)
    return result
