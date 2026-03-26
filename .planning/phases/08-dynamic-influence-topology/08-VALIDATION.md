---
phase: 8
slug: dynamic-influence-topology
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/ -x -q --timeout=30` |
| **Full suite command** | `uv run pytest tests/ -v --timeout=60` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q --timeout=30`
- **After every plan wave:** Run `uv run pytest tests/ -v --timeout=60`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | SIM-07 | unit | `uv run pytest tests/test_influence.py -x -q` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | SIM-07 | unit | `uv run pytest tests/test_influence.py -x -q` | ❌ W0 | ⬜ pending |
| 08-02-01 | 02 | 1 | SIM-08 | unit | `uv run pytest tests/test_simulation.py -x -q` | ✅ | ⬜ pending |
| 08-02-02 | 02 | 1 | INFRA-10 | unit | `uv run pytest tests/test_miro.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_influence.py` — stubs for SIM-07 influence edge computation and bracket-diverse peer selection
- [ ] `tests/test_miro.py` — stubs for INFRA-10 Miro batcher stub types and interface

*Existing test infrastructure (pytest, conftest.py) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Influence topology queryable in Neo4j | SIM-07 | Requires running Neo4j instance | Run simulation, then query: `MATCH (a:Agent)-[r:INFLUENCED_BY]->(b:Agent) RETURN a.id, r.weight, b.id LIMIT 10` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
