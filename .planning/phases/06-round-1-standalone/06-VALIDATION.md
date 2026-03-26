---
phase: 6
slug: round-1-standalone
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | SIM-04-a | unit | `uv run pytest tests/test_simulation.py::test_run_round1_dispatches_with_no_peer_context -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | SIM-04-b | unit | `uv run pytest tests/test_simulation.py::test_run_round1_loads_worker_after_orchestrator -x` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | SIM-04-c | unit | `uv run pytest tests/test_simulation.py::test_run_round1_unloads_worker_on_error -x` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 1 | SIM-04-d | unit | `uv run pytest tests/test_simulation.py::test_run_round1_persists_decisions_round_1 -x` | ❌ W0 | ⬜ pending |
| 06-01-05 | 01 | 1 | SIM-04-e | unit | `uv run pytest tests/test_simulation.py::test_run_round1_passes_raw_rumor_to_agents -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | SIM-04-f | unit | `uv run pytest tests/test_cli.py::test_parse_run_args -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 1 | SIM-04-g | unit | `uv run pytest tests/test_cli.py::test_main_run_calls_asyncio_run -x` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 1 | SIM-04-h | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_bracket_table -x` | ❌ W0 | ⬜ pending |
| 06-02-04 | 02 | 1 | SIM-04-i | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_notable_decisions -x` | ❌ W0 | ⬜ pending |
| 06-02-05 | 02 | 1 | SIM-04-j | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_header_with_failures -x` | ❌ W0 | ⬜ pending |
| 06-02-06 | 02 | 1 | SIM-04-k | unit | `uv run pytest tests/test_cli.py::test_bracket_aggregation_excludes_parse_errors -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_simulation.py` — stubs for SIM-04-a through SIM-04-e (pipeline unit tests with mocked dependencies)
- [ ] New tests in `tests/test_cli.py` — stubs for SIM-04-f through SIM-04-k (CLI handler and report formatting)
- No new framework install needed — pytest-asyncio already configured with `asyncio_mode = "auto"`
- No new conftest fixtures needed beyond existing patterns (mock_governor, sample_personas)

*Existing infrastructure covers framework requirements.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
