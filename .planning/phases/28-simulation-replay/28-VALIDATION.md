---
phase: 28
slug: simulation-replay
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_state.py tests/test_graph.py tests/test_tui.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_state.py tests/test_graph.py tests/test_tui.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 28-??-01 | TBD | 0 | REPLAY-01a | — | N/A | unit (mock) | `uv run pytest tests/test_graph.py::test_read_full_cycle_signals -x` | ❌ W0 | ⬜ pending |
| 28-??-02 | TBD | 0 | REPLAY-01b | — | N/A | unit (mock) | `uv run pytest tests/test_graph.py::test_read_completed_cycles -x` | ❌ W0 | ⬜ pending |
| 28-??-03 | TBD | 0 | REPLAY-01c | — | N/A | unit | `uv run pytest tests/test_state.py::test_replay_store_snapshot -x` | ❌ W0 | ⬜ pending |
| 28-??-04 | TBD | 0 | REPLAY-01d | — | N/A | unit | `uv run pytest tests/test_state.py::test_replay_store_round_advance -x` | ❌ W0 | ⬜ pending |
| 28-??-05 | TBD | 0 | REPLAY-01e | — | N/A | unit | `uv run pytest tests/test_state.py::test_simulation_phase_replay -x` | ❌ W0 | ⬜ pending |
| 28-??-06 | TBD | 0 | REPLAY-01f | — | N/A | unit | `uv run pytest tests/test_tui.py::test_header_replay_format -x` | ❌ W0 | ⬜ pending |
| 28-??-07 | TBD | 0 | REPLAY-01g | — | N/A | unit | `uv run pytest tests/test_cli.py::test_replay_subcommand -x` | ❌ W0 | ⬜ pending |
| 28-??-08 | TBD | integration | REPLAY-01h | — | N/A | integration | `uv run pytest tests/test_graph_integration.py::test_full_cycle_signals_perf -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Note: Task IDs (28-??-NN) will be updated by the executor once PLAN.md files assign concrete IDs.*

---

## Wave 0 Requirements

- [ ] `tests/test_state.py` — add `ReplayStore` unit tests: `test_replay_store_snapshot`, `test_replay_store_round_advance`, `test_simulation_phase_replay`
- [ ] `tests/test_graph.py` — add mock-based tests: `test_read_full_cycle_signals`, `test_read_completed_cycles`, `test_read_bracket_narratives_for_round`
- [ ] `tests/test_tui.py` — add `test_header_replay_format`, `test_agent_cell_disabled_during_replay`
- [ ] `tests/test_cli.py` — add `test_replay_subcommand` (argument parsing only, no inference)
- [ ] `tests/test_graph_integration.py` — add `test_full_cycle_signals_perf` (requires live Neo4j, marked `@pytest.mark.integration`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TUI replay visual distinction: header badge amber `REPLAY — Cycle {id}` | REPLAY-01 | Requires running the full TUI — not automatable in CI | 1. Run `uv run alphaswarm replay --cycle <id>`. 2. Confirm header shows amber "REPLAY — Cycle {short_id}". 3. Confirm footer shows `P: Play/Pause  Space/→: Next  Esc: Exit`. |
| Auto-advance 3s timer steps Round 1 → Round 2 → Round 3 | REPLAY-01 | Requires interactive TUI session with real timing | 1. Start replay in auto mode. 2. Observe rounds advance automatically ~3s apart. 3. Confirm grid cells update to correct signals per round. |
| `P` key toggles auto/manual; `Space`/`→` advances in manual mode | REPLAY-01 | Key binding interaction is not automatable in headless mode | 1. Press `P` — observe `[PAUSED]` indicator. 2. Press `Space` — confirm single round advance. 3. Press `P` again — confirm `[AUTO]` resumes. |
| Cypher `read_full_cycle_signals()` < 2s on 600+ node graph | REPLAY-01 | Requires live Neo4j with populated simulation data | 1. Run `uv run alphaswarm replay --cycle <id-with-600-nodes>`. 2. Observe load time in logs. 3. Check structlog output for `duration_ms < 2000`. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
