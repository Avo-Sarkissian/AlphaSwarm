---
phase: 7
slug: rounds-2-3-peer-influence-and-consensus
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `uv run pytest tests/test_simulation.py -x` |
| **Full suite command** | `uv run pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_simulation.py tests/test_batch_dispatcher.py tests/test_cli.py -x`
- **After every plan wave:** Run `uv run pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | SIM-05 | unit | `uv run pytest tests/test_simulation.py::test_format_peer_context_structure -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | SIM-05 | unit | `uv run pytest tests/test_simulation.py::test_dispatch_round_reads_peers_per_agent -x` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 1 | SIM-05 | unit | `uv run pytest tests/test_batch_dispatcher.py::test_dispatch_wave_per_agent_peer_contexts -x` | ❌ W0 | ⬜ pending |
| 07-01-04 | 01 | 1 | SIM-05 | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_round2_uses_round1_peers -x` | ❌ W0 | ⬜ pending |
| 07-02-01 | 02 | 1 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_round3_uses_round2_peers -x` | ❌ W0 | ⬜ pending |
| 07-02-02 | 02 | 1 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_returns_complete_result -x` | ❌ W0 | ⬜ pending |
| 07-02-03 | 02 | 1 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_simulation_result_is_frozen -x` | ❌ W0 | ⬜ pending |
| 07-02-04 | 02 | 1 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_persists_all_rounds -x` | ❌ W0 | ⬜ pending |
| 07-03-01 | 03 | 1 | SIM-05 | unit | `uv run pytest tests/test_simulation.py::test_compute_shifts_signal_flips -x` | ❌ W0 | ⬜ pending |
| 07-03-02 | 03 | 1 | SIM-05 | unit | `uv run pytest tests/test_simulation.py::test_compute_shifts_bracket_confidence -x` | ❌ W0 | ⬜ pending |
| 07-04-01 | 04 | 2 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_simulation_phase_transitions -x` | ❌ W0 | ⬜ pending |
| 07-04-02 | 04 | 2 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_worker_reload_once_for_rounds_2_3 -x` | ❌ W0 | ⬜ pending |
| 07-04-03 | 04 | 2 | SIM-06 | unit | `uv run pytest tests/test_simulation.py::test_governor_fresh_session_rounds_2_3 -x` | ❌ W0 | ⬜ pending |
| 07-05-01 | 05 | 2 | SIM-06 | unit | `uv run pytest tests/test_cli.py::test_run_pipeline_calls_run_simulation -x` | ❌ W0 | ⬜ pending |
| 07-05-02 | 05 | 2 | SIM-06 | unit | `uv run pytest tests/test_cli.py::test_shift_analysis_output -x` | ❌ W0 | ⬜ pending |
| 07-05-03 | 05 | 2 | SIM-06 | unit | `uv run pytest tests/test_cli.py::test_simulation_summary_output -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_simulation.py` — extend with `run_simulation()`, `SimulationResult`, `_format_peer_context()`, `_dispatch_round()`, `_compute_shifts()`, `ShiftMetrics` test stubs
- [ ] `tests/test_batch_dispatcher.py` — extend with `peer_contexts` list parameter test stub
- [ ] `tests/test_cli.py` — extend with shift analysis and simulation summary output test stubs
- [ ] No new test files needed — all tests extend existing files
- [ ] No framework install needed — pytest-asyncio already configured

*Existing infrastructure covers framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Observable opinion shifts between rounds | SIM-05 | Depends on LLM output variability | Run full simulation with real Ollama models, inspect per-round bracket tables for signal flips |
| Echo chamber convergence toward Sovereign consensus | SIM-06 | Emergent behavior from static influence weights | Run simulation, verify Sovereign bracket dominates final consensus direction |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
