---
phase: 29
slug: fastapi-skeleton-and-event-loop-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0 + pytest-asyncio 0.24 |
| **Config file** | `pyproject.toml` — `asyncio_mode = "auto"`, `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/test_state.py tests/test_web.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/test_state.py -x -q`
- **After web tasks:** `uv run pytest tests/test_state.py tests/test_web.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test | File |
|--------|----------|------|------|
| BE-01 | `alphaswarm web` starts Uvicorn; GET /api/health returns 200 with simulation_phase, memory_percent, is_simulation_running | `tests/test_web.py::test_health_endpoint` | Wave 0 |
| BE-01 | All stateful objects created inside lifespan, not at module import | `tests/test_web.py::test_lifespan_creates_objects_inside_loop` | Wave 0 |
| BE-02 | `StateStore.snapshot()` called twice returns identical data (rationale_entries=() both times) | `tests/test_state.py::test_snapshot_non_destructive` | Wave 0 |
| BE-02 | `drain_rationales(5)` removes entries; second call returns fewer | `tests/test_state.py::test_drain_rationales` | Wave 0 |
| BE-02 | TUI `_poll_snapshot` behavior preserved via `drain_rationales(5)` | `tests/test_state.py::test_drain_rationales_tui_compat` | Wave 0 |
| BE-03 | Second WebSocket client does not drain rationale entries first client should receive | `tests/test_web.py::test_websocket_queue_isolation` | Wave 0 |
| BE-03 | Slow client overflow: oldest dropped, newest survives | `tests/test_web.py::test_connection_manager_drop_oldest` | Wave 0 |
| BE-03 | Client disconnect cancels writer task cleanly | `tests/test_web.py::test_connection_manager_disconnect_cancels_task` | Wave 0 |
| SC-4 | POST /api/simulate/start while running returns HTTP 409 | `tests/test_web.py::test_simulation_manager_409_guard` | Wave 0 |

---

## Existing Tests (must remain green)

```bash
uv run pytest tests/test_state.py -x -q   # 28 tests — must still pass after snapshot() refactor
```

**Breaking change warning:** `test_rationale_queue_drain` and `test_snapshot_drain_queue_twice` assert `snapshot()` drains the queue. These MUST be updated in the same task as the StateStore refactor.

---

## Wave 0 Gaps

- [ ] `tests/test_web.py` — create with 6 tests: health endpoint, lifespan object creation, SimulationManager 409 guard, ConnectionManager queue isolation, drop-oldest overflow, disconnect task cancellation
- [ ] `tests/test_state.py` — add 3 new tests (`test_snapshot_non_destructive`, `test_drain_rationales`, `test_drain_rationales_tui_compat`); update 2 existing drain tests to use `drain_rationales()`
- [ ] Framework install: `uv add "fastapi>=0.115" "uvicorn[standard]>=0.34"` — must run before any web code is importable
