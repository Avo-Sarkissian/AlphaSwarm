---
phase: 35
slug: agent-interviews-web-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (auto mode) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_web_interview.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_web_interview.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 35-01-01 | 01 | 0 | WEB-06 | — | N/A | unit | `uv run pytest tests/test_web_interview.py -x -q` | ❌ W0 | ⬜ pending |
| 35-01-02 | 01 | 1 | WEB-06-SC1 | — | 503 when services None | unit | `uv run pytest tests/test_web_interview.py::test_interview_endpoint_returns_response -x` | ❌ W0 | ⬜ pending |
| 35-01-03 | 01 | 1 | WEB-06-SC3 | — | Session reuse per agent | unit | `uv run pytest tests/test_web_interview.py::test_interview_multi_turn -x` | ❌ W0 | ⬜ pending |
| 35-01-04 | 01 | 1 | WEB-06 | — | 503 no graph_manager | unit | `uv run pytest tests/test_web_interview.py::test_interview_503_no_graph -x` | ❌ W0 | ⬜ pending |
| 35-01-05 | 01 | 1 | WEB-06 | — | 503 no ollama_client | unit | `uv run pytest tests/test_web_interview.py::test_interview_503_no_ollama -x` | ❌ W0 | ⬜ pending |
| 35-01-06 | 01 | 1 | WEB-06 | — | 404 no completed cycles | unit | `uv run pytest tests/test_web_interview.py::test_interview_404_no_cycles -x` | ❌ W0 | ⬜ pending |
| 35-02-01 | 02 | 2 | WEB-06-SC2 | — | N/A | manual | N/A | N/A | ⬜ pending |
| 35-02-02 | 02 | 2 | WEB-06-SC4 | — | N/A | manual | N/A | N/A | ⬜ pending |
| 35-02-03 | 02 | 2 | WEB-06-SC5 | — | N/A | manual | N/A | N/A | ⬜ pending |
| 35-03-01 | 03 | 3 | WEB-06 | — | N/A | manual | N/A | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web_interview.py` — stubs for WEB-06 SC-1, SC-3, and all error cases (503 no graph, 503 no ollama, 404 no cycles, session reuse)
- [ ] `tests/test_web.py` — update `_make_test_app()` helper to register interview router and init `interview_sessions` dict on `app.state`

*Wave 0 must create these files before backend route implementation begins.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Clicking node in complete state opens interview panel | WEB-06-SC2 | Vue component visual interaction — requires browser | Run simulation to completion, click any agent node, verify InterviewPanel slides in |
| Panel dismissible, force graph interactive behind it | WEB-06-SC4 | Vue layout z-index — requires browser | Open interview panel, click X, verify panel closes and ForceGraph/AgentSidebar remain interactive |
| Loading indicator while LLM responds | WEB-06-SC5 | Vue UI state during async fetch — requires browser | Send interview message, verify Send button is disabled and "Thinking..." appears before response |
| Full interview flow end-to-end | WEB-06 | Integration — requires Ollama + Neo4j running | Start app, run simulation, open interview panel, ask 2+ questions, verify multi-turn responses |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
