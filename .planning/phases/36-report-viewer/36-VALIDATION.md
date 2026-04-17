---
phase: 36
slug: report-viewer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest` >= 8.0 with `pytest-asyncio` >= 0.24 (`asyncio_mode = auto`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_web.py -x` |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~5s (web subset), ~60s (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_web.py -x`
- **After every plan wave:** Run `pytest`
- **Before `/gsd-verify-work`:** Full suite must be green + manual frontend smoke test
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 36-01-01 | 01 | 1 | WEB-06 | T-36-01 | cycle_id validated against `^[a-zA-Z0-9_-]+$` — rejects traversal | unit | `pytest tests/test_web.py::test_get_report_returns_content -x` | ❌ W0 | ⬜ pending |
| 36-01-02 | 01 | 1 | WEB-06 | — | 404 when report file missing | unit | `pytest tests/test_web.py::test_get_report_404_when_missing -x` | ❌ W0 | ⬜ pending |
| 36-01-03 | 01 | 1 | WEB-06 | — | 409 when phase != COMPLETE | unit | `pytest tests/test_web.py::test_generate_report_409_wrong_phase -x` | ❌ W0 | ⬜ pending |
| 36-01-04 | 01 | 1 | WEB-06 | — | 409 when report task in-progress | unit | `pytest tests/test_web.py::test_generate_report_409_in_progress -x` | ❌ W0 | ⬜ pending |
| 36-01-05 | 01 | 1 | WEB-06 | — | 202 + spawns background task | unit | `pytest tests/test_web.py::test_generate_report_202_spawns_task -x` | ❌ W0 | ⬜ pending |
| 36-01-06 | 01 | 1 | WEB-06 | — | 503 when graph/ollama unavailable | unit | `pytest tests/test_web.py::test_generate_report_503_no_services -x` | ❌ W0 | ⬜ pending |
| 36-01-07 | 01 | 1 | REPORT-02 | — | Background task calls ReportEngine → ReportAssembler → write_report → write_sentinel in order | unit | `pytest tests/test_web.py::test_report_generation_pipeline -x` | ❌ W0 | ⬜ pending |
| 36-01-08 | 01 | 1 | WEB-06 | — | Orchestrator unloaded in `finally` even on exception | unit | `pytest tests/test_web.py::test_report_generation_unloads_on_error -x` | ❌ W0 | ⬜ pending |
| 36-02-01 | 02 | 2 | WEB-06 | — | marked + DOMPurify sanitizes output (no `<script>` tags) | manual | n/a | n/a | ⬜ pending |
| 36-02-02 | 02 | 2 | WEB-06 | — | Escape/backdrop click/X closes modal | manual | n/a | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web.py` — add 8 new tests: `test_get_report_returns_content`, `test_get_report_404_when_missing`, `test_generate_report_409_wrong_phase`, `test_generate_report_409_in_progress`, `test_generate_report_202_spawns_task`, `test_generate_report_503_no_services`, `test_report_generation_pipeline`, `test_report_generation_unloads_on_error`
- [ ] Test fixtures: temp `reports/` directory with `tmp_path` fixture cleanup
- [ ] Mock helpers for `ReportEngine.run`, `write_report`, `write_sentinel` to isolate routes from Phase 15 logic

*No frontend test infrastructure gap — Phase 36 follows the project's existing pattern (no Vue component tests). Manual acceptance testing covers WEB-06 frontend behavior, consistent with phases 29–35.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| marked + DOMPurify sanitization | WEB-06 | No frontend test framework in project | Open report with known markdown; verify rendered HTML has no `<script>` tags |
| Modal open/close (Escape, backdrop, X) | WEB-06 | UI interaction | Click all three close mechanisms; verify modal dismisses |
| Empty state → Generate → poll → complete flow | WEB-06 | Full async flow requires live simulation | Run simulation to COMPLETE, open report panel, click Generate Report, wait for completion, verify rendered sections |
| "Regenerate Report" footer state on reopen | WEB-06 | State-dependent UI | Close and reopen modal after report exists; verify footer shows Regenerate button |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
