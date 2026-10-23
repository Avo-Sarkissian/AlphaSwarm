"""Per-round telemetry, governor metrics and the transition probe (docs/DECISIONS.md#adr-inference-telemetry)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import alphaswarm.telemetry as telemetry_module
from alphaswarm.inference.types import InferenceResult
from alphaswarm.telemetry import (
    COLD_LOAD_MS,
    CTX_WARNING_FRACTION,
    GovernorTelemetrySource,
    RoundTelemetry,
    docker_vm_rss_mb,
    governor_metrics,
    make_transition_probe,
    percentile,
)


def _result(**fields: Any) -> InferenceResult:
    return InferenceResult(content="{}", model="alphaswarm-worker", **fields)


def test_thresholds() -> None:
    assert (COLD_LOAD_MS, CTX_WARNING_FRACTION) == (500.0, 0.9)


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert (percentile(values, 50), percentile(values, 95)) == (50.0, 95.0)
    assert percentile([7.0], 95) == 7.0


def test_percentile_rejects_an_empty_sequence() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


def test_round_metrics_from_local_calls() -> None:
    t = RoundTelemetry(num_ctx=4096)
    for latency in (1000.0, 2000.0, 3000.0, 4000.0):
        t.record(
            _result(
                input_tokens=1400,
                output_tokens=150,
                prefill_ms=600.0,
                decode_ms=2700.0,
                load_ms=0.0,
                finish_reason="stop",
            ),
            latency_ms=latency,
        )
    t.record(
        _result(
            input_tokens=3700,
            output_tokens=400,
            prefill_ms=1600.0,
            decode_ms=7100.0,
            load_ms=4200.0,
            finish_reason="length",
        ),
        latency_ms=9000.0,
    )
    assert t.calls == 5
    assert t.to_metrics(2) == {
        "r2_latency_p50_ms": 3000.0,
        "r2_latency_p95_ms": 9000.0,
        "r2_mean_prompt_tokens": 1860.0,
        "r2_mean_completion_tokens": 200.0,
        "r2_mean_prefill_ms": 800.0,
        "r2_mean_decode_ms": 3580.0,
        "r2_total_load_ms": 4200.0,
        "r2_cold_loads": 1,
        "r2_truncations": 1,
        "r2_ctx_warnings": 1,  # 3700 >= 0.9 * 4096
    }


def test_unreported_fields_are_omitted_not_zero() -> None:
    t = RoundTelemetry(num_ctx=None)  # a cloud worker: no context window to check
    t.record(_result(input_tokens=1500, output_tokens=300, finish_reason="length"), latency_ms=800.0)
    m = t.to_metrics(1)
    assert {"r1_mean_prefill_ms", "r1_mean_decode_ms", "r1_total_load_ms"}.isdisjoint(m)
    assert (m["r1_mean_prompt_tokens"], m["r1_mean_completion_tokens"]) == (1500.0, 300.0)
    assert (m["r1_truncations"], m["r1_cold_loads"], m["r1_ctx_warnings"]) == (1, 0, 0)
    assert m["r1_latency_p50_ms"] == m["r1_latency_p95_ms"] == 800.0


def test_a_round_without_calls_writes_only_counts() -> None:
    assert RoundTelemetry().to_metrics(3) == {
        "r3_cold_loads": 0,
        "r3_truncations": 0,
        "r3_ctx_warnings": 0,
    }


class _Governor:
    def __init__(self, seconds: dict[str, float], peak: float) -> None:
        self._seconds = seconds
        self._peak = peak

    def time_in_state(self) -> dict[str, float]:
        return dict(self._seconds)

    @property
    def peak_memory_percent(self) -> float:
        return self._peak


def test_governor_metrics_from_a_telemetry_source() -> None:
    gov = _Governor({"throttled": 12.34, "paused": 0.0, "crisis": 1.06}, 91.27)
    assert isinstance(gov, GovernorTelemetrySource)
    assert governor_metrics(gov) == {
        "governor_throttled_seconds": 12.3,
        "governor_paused_seconds": 0.0,
        "governor_crisis_seconds": 1.1,
        "governor_peak_memory_percent": 91.3,
    }


def test_objects_without_numeric_telemetry_add_no_keys() -> None:
    assert governor_metrics(object()) == {}
    assert governor_metrics(MagicMock()) == {}  # attributes exist but are not numbers


def test_docker_vm_rss_sums_vm_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    procs = [
        SimpleNamespace(
            info={
                "name": "com.apple.Virtualization.VirtualMachine",
                "memory_info": SimpleNamespace(rss=2 * 1024**3),
            }
        ),
        SimpleNamespace(info={"name": "python3", "memory_info": SimpleNamespace(rss=10**9)}),
        SimpleNamespace(info={"name": "com.apple.Virtualization.VirtualMachine", "memory_info": None}),
    ]
    monkeypatch.setattr(telemetry_module.psutil, "process_iter", lambda attrs: iter(procs))
    assert docker_vm_rss_mb() == 2048.0


def test_docker_vm_rss_is_none_without_a_vm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_module.psutil, "process_iter", lambda attrs: iter([]))
    assert docker_vm_rss_mb() is None


async def test_transition_probe_reports_models_and_vm_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_module, "docker_vm_rss_mb", lambda: 2048.0)

    async def loaded() -> list[str]:
        return ["llama3:8b", "alphaswarm-worker"]

    assert await make_transition_probe(loaded)() == {
        "loaded_models": "alphaswarm-worker,llama3:8b",
        "docker_vm_rss_mb": 2048.0,
    }


async def test_transition_probe_with_nothing_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_module, "docker_vm_rss_mb", lambda: None)

    async def loaded() -> list[str]:
        return []

    assert await make_transition_probe(loaded)() == {"loaded_models": "-", "docker_vm_rss_mb": None}


async def test_transition_probe_without_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_module, "docker_vm_rss_mb", lambda: None)
    assert await make_transition_probe(None)() == {"loaded_models": None, "docker_vm_rss_mb": None}
