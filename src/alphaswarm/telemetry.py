"""Per-round inference telemetry and governor telemetry for the cycle metrics.

``RoundTelemetry`` turns one round's worker calls into the ``r{n}_*`` keys of
metrics_version 2; ``governor_metrics`` reads a governor's time-in-state;
``make_transition_probe`` builds the context logged when the governor changes
state (docs/DECISIONS.md#adr-inference-telemetry).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

import psutil

from alphaswarm.types import GovernorTelemetryState

if TYPE_CHECKING:
    from alphaswarm.inference.types import InferenceResult

# A call that paid at least this much model-load time counts as a cold load.
COLD_LOAD_MS: Final = 500.0
# A prompt at or above this share of the context window is flagged.
CTX_WARNING_FRACTION: Final = 0.9
# Docker Desktop VM process names on macOS (Apple Virtualization, QEMU, older backends).
DOCKER_VM_PROCESS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "com.apple.Virtualization.VirtualMachine",
        "qemu-system-aarch64",
        "com.docker.hyperkit",
        "com.docker.krun",
    }
)

LoadedModels = Callable[[], Awaitable[Sequence[str]]]


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile of ``values`` (``pct`` in (0, 100])."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


class RoundTelemetry:
    """Aggregates one round's worker calls into the ``r{n}_*`` cycle-metric keys."""

    def __init__(self, *, num_ctx: int | None = None) -> None:
        self._num_ctx = num_ctx
        self._latencies: list[float] = []
        self._prompt_tokens: list[float] = []
        self._completion_tokens: list[float] = []
        self._prefill_ms: list[float] = []
        self._decode_ms: list[float] = []
        self._load_ms: list[float] = []
        self._cold_loads = 0
        self._truncations = 0
        self._ctx_warnings = 0

    @property
    def calls(self) -> int:
        """Number of completed calls recorded so far."""
        return len(self._latencies)

    def record(self, result: InferenceResult, *, latency_ms: float) -> None:
        """Add one completed call. Fields the provider did not report are skipped."""
        self._latencies.append(latency_ms)
        if result.input_tokens is not None:
            self._prompt_tokens.append(float(result.input_tokens))
            if self._num_ctx is not None and result.input_tokens >= CTX_WARNING_FRACTION * self._num_ctx:
                self._ctx_warnings += 1
        if result.output_tokens is not None:
            self._completion_tokens.append(float(result.output_tokens))
        if result.prefill_ms is not None:
            self._prefill_ms.append(result.prefill_ms)
        if result.decode_ms is not None:
            self._decode_ms.append(result.decode_ms)
        if result.load_ms is not None:
            self._load_ms.append(result.load_ms)
            if result.load_ms >= COLD_LOAD_MS:
                self._cold_loads += 1
        if result.finish_reason == "length":
            self._truncations += 1

    def to_metrics(self, round_num: int) -> dict[str, float | int]:
        """The round's metric keys; unknown means are omitted, never written as 0."""
        prefix = f"r{round_num}_"
        metrics: dict[str, float | int] = {}
        if self._latencies:
            metrics[f"{prefix}latency_p50_ms"] = round(percentile(self._latencies, 50), 1)
            metrics[f"{prefix}latency_p95_ms"] = round(percentile(self._latencies, 95), 1)
        for key, values in (
            ("mean_prompt_tokens", self._prompt_tokens),
            ("mean_completion_tokens", self._completion_tokens),
            ("mean_prefill_ms", self._prefill_ms),
            ("mean_decode_ms", self._decode_ms),
        ):
            mean = _mean(values)
            if mean is not None:
                metrics[f"{prefix}{key}"] = mean
        if self._load_ms:
            metrics[f"{prefix}total_load_ms"] = round(sum(self._load_ms), 1)
        metrics[f"{prefix}cold_loads"] = self._cold_loads
        metrics[f"{prefix}truncations"] = self._truncations
        metrics[f"{prefix}ctx_warnings"] = self._ctx_warnings
        return metrics


@runtime_checkable
class GovernorTelemetrySource(Protocol):
    """A concurrency controller that tracks memory pressure (the local governor)."""

    def time_in_state(self) -> dict[GovernorTelemetryState, float]: ...

    @property
    def peak_memory_percent(self) -> float: ...


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def governor_metrics(controller: object) -> dict[str, float]:
    """``governor_*`` cycle-metric keys, or ``{}`` for controllers without telemetry."""
    if not isinstance(controller, GovernorTelemetrySource):
        return {}
    seconds = controller.time_in_state()
    values = {
        "governor_throttled_seconds": _number(seconds.get("throttled")),
        "governor_paused_seconds": _number(seconds.get("paused")),
        "governor_crisis_seconds": _number(seconds.get("crisis")),
        "governor_peak_memory_percent": _number(controller.peak_memory_percent),
    }
    if any(v is None for v in values.values()):
        return {}
    return {key: round(v, 1) for key, v in values.items() if v is not None}


def docker_vm_rss_mb() -> float | None:
    """Resident memory of the Docker Desktop VM in MB, or None when no VM process runs.

    Blocking (walks the process table): call it through ``asyncio.to_thread``.
    """
    total = 0
    found = False
    for proc in psutil.process_iter(["name", "memory_info"]):
        info = proc.info
        mem = info.get("memory_info")
        if info.get("name") in DOCKER_VM_PROCESS_NAMES and mem is not None:
            total += int(mem.rss)
            found = True
    return round(total / 1_048_576, 1) if found else None


def make_transition_probe(
    loaded_models: LoadedModels | None,
) -> Callable[[], Awaitable[dict[str, str | float | None]]]:
    """Build the context the governor logs on each state change (docs/DECISIONS.md#adr-inference-telemetry)."""

    async def probe() -> dict[str, str | float | None]:
        models: str | None = None
        if loaded_models is not None:
            names = await loaded_models()
            models = ",".join(sorted(names)) if names else "-"
        rss = await asyncio.to_thread(docker_vm_rss_mb)
        return {"loaded_models": models, "docker_vm_rss_mb": rss}

    return probe
