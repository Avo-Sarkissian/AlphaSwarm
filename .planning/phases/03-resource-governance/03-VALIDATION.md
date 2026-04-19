---
phase: 3
slug: resource-governance
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-24
---

# Phase 3 -- Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `uv run pytest tests/ -x -q --timeout=10` |
| **Full suite command** | `uv run pytest tests/ -v --timeout=30` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q --timeout=10`
- **After every plan wave:** Run `uv run pytest tests/ -v --timeout=30`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | INFRA-01 | unit | `uv run pytest tests/test_governor.py -k token_pool -v` | -- W0 (inline TDD) | pending |
| 03-01-02 | 01 | 1 | INFRA-02 | unit | `uv run pytest tests/test_governor.py -k memory_monitor -v` | -- W0 (inline TDD) | pending |
| 03-02-01 | 02 | 2 | INFRA-07 | unit | `uv run pytest tests/test_batch_dispatcher.py -v` | -- W0 (inline TDD) | pending |
| 03-02-02 | 02 | 2 | INFRA-09 | unit | `uv run pytest tests/test_batch_dispatcher.py -k failure_rate -v` | -- W0 (inline TDD) | pending |

*Status: pending / green / red / flaky*

*Note: All Plan tasks use inline TDD (tdd="true") which satisfies the Wave 0 / Nyquist requirement -- tests are written RED-first within each task, not in a separate Wave 0 plan.*

---

## Wave 0 Requirements

- [x] `tests/test_governor.py` -- created inline by Plan 03-01 Task 2 (TDD RED phase)
- [x] `tests/test_memory_monitor.py` -- created inline by Plan 03-01 Task 1 (TDD RED phase)
- [x] `tests/test_batch_dispatcher.py` -- created inline by Plan 03-02 Task 1 (TDD RED phase)

*Existing test infrastructure (pytest, pytest-asyncio) covers framework needs. Inline TDD satisfies Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Memory pressure response under real load | INFRA-02 | Requires actual memory pressure on M1 Max | Run 100-agent simulation, monitor psutil + sysctl output, verify throttle at 80% |
| Crisis abort after sustained pressure | INFRA-02 | Requires sustained OOM-level pressure for 5 minutes | Artificially constrain memory, verify abort after timeout |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (inline TDD satisfies)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
