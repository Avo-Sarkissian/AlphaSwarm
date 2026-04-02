---
phase: 15
slug: post-simulation-report
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_report.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_report.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 0 | REPORT-01 | unit | `pytest tests/test_report.py::TestParseActionInput -x` | ❌ W0 | ⬜ pending |
| 15-01-02 | 01 | 0 | REPORT-01 | unit | `pytest tests/test_report.py::TestReportEngine::test_terminates_on_final_answer -x` | ❌ W0 | ⬜ pending |
| 15-01-03 | 01 | 0 | REPORT-01 | unit | `pytest tests/test_report.py::TestReportEngine::test_hard_cap_termination -x` | ❌ W0 | ⬜ pending |
| 15-01-04 | 01 | 0 | REPORT-01 | unit | `pytest tests/test_report.py::TestReportEngine::test_duplicate_call_terminates -x` | ❌ W0 | ⬜ pending |
| 15-01-05 | 01 | 1 | REPORT-02 | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_read_consensus_summary -x` | ❌ W0 | ⬜ pending |
| 15-01-06 | 01 | 1 | REPORT-02 | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_influence_leaders_round_filter -x` | ❌ W0 | ⬜ pending |
| 15-01-07 | 01 | 1 | REPORT-02 | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_signal_flip_none_filter -x` | ❌ W0 | ⬜ pending |
| 15-02-01 | 02 | 1 | REPORT-03 | unit | `pytest tests/test_report.py::TestReportAssembler::test_renders_section -x` | ❌ W0 | ⬜ pending |
| 15-02-02 | 02 | 1 | REPORT-03 | unit | `pytest tests/test_report.py::TestReportAssembler::test_async_file_write -x` | ❌ W0 | ⬜ pending |
| 15-02-03 | 02 | 1 | REPORT-03 | unit | `pytest tests/test_report.py::TestReportAssembler::test_sentinel_file_schema -x` | ❌ W0 | ⬜ pending |
| 15-02-04 | 02 | 1 | REPORT-03 | unit | `pytest tests/test_cli.py::test_report_subcommand_registered -x` | ✅ | ⬜ pending |
| 15-02-05 | 02 | 2 | REPORT-03 | unit | `pytest tests/test_tui.py::test_sentinel_poll_updates_footer -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_report.py` — stubs for REPORT-01 (ReACT engine tests), REPORT-02 (Cypher query tool tests), REPORT-03 (assembler + sentinel + CLI tests)
- [ ] `src/alphaswarm/report.py` — new module (new file, required for import in test stubs)
- [ ] `src/alphaswarm/templates/report/` — directory + 8 `.j2` template stubs
- [ ] `pyproject.toml` — add `jinja2>=3.1.6` and `aiofiles>=25.1.0` to `[project.dependencies]`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Structured Markdown report is human-readable and analytically useful | REPORT-03 | Aesthetic and content quality cannot be machine-asserted | Run `alphaswarm report --cycle <cycle_id>` after a full simulation; open output `.md` file and verify all 8 sections present with plausible data |
| TUI displays report path after generation | REPORT-03 | Requires live TUI session | Run `alphaswarm tui` in background; run `alphaswarm report --cycle <id>`; verify footer updates with path |
| Model lifecycle: report cannot overlap simulation | REPORT-05 (informational) | Requires two terminal sessions | Verify CLI warning prints if report started manually during simulation |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
