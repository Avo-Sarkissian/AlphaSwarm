---
phase: 14
slug: agent-interviews
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest-asyncio |
| **Config file** | `pytest.ini` or `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/ -x -q --tb=short` |
| **Full suite command** | `uv run pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `uv run pytest tests/ -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | INT-01 | unit | `uv run pytest tests/test_interview_context.py -x -q` | ❌ W0 | ⬜ pending |
| 14-01-02 | 01 | 1 | INT-01 | unit | `uv run pytest tests/test_interview_context.py -x -q` | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 2 | INT-02 | unit | `uv run pytest tests/test_interview_engine.py -x -q` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 2 | INT-02 | unit | `uv run pytest tests/test_interview_engine.py -x -q` | ❌ W0 | ⬜ pending |
| 14-03-01 | 03 | 3 | INT-03 | manual | N/A — TUI interaction | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_interview_context.py` — stubs for INT-01 (Neo4j context reconstruction)
- [ ] `tests/test_interview_engine.py` — stubs for INT-02 (sliding window, in-character response)
- [ ] `tests/conftest.py` — shared fixtures (mock Neo4j driver, mock OllamaClient)

*Existing test infrastructure is in place; only new stubs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Click agent cell opens InterviewScreen | INT-03 | TUI mouse interaction, no headless driver | Run simulation, click any agent cell, verify overlay appears |
| Exit interview returns to dashboard | INT-03 | TUI keyboard/button interaction | Press Escape or click Exit, verify dashboard state unchanged |
| "Loading model..." feedback appears | INT-02 | Real Ollama model load timing | Open interview screen, observe loading message before first response |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
