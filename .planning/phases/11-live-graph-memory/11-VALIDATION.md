---
phase: 11
slug: live-graph-memory
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `uv run pytest tests/test_graph.py tests/test_write_buffer.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_graph.py tests/test_write_buffer.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | GRAPH-02 | unit | `uv run pytest tests/test_graph.py -k rationale_episode -x -q` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | GRAPH-03 | unit | `uv run pytest tests/test_graph.py -k narrative_references -x -q` | ❌ W0 | ⬜ pending |
| 11-01-03 | 01 | 1 | GRAPH-01 | unit | `uv run pytest tests/test_write_buffer.py -x -q` | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 2 | GRAPH-01 | integration | `uv run pytest tests/test_simulation.py -k live_graph -x -q` | ❌ W0 | ⬜ pending |
| 11-02-02 | 02 | 2 | GRAPH-02 | integration | `uv run pytest tests/test_simulation.py -k rationale_episode -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_write_buffer.py` — stubs for WriteBuffer queue/flush/drain
- [ ] `tests/test_graph.py` — extend with rationale episode and narrative edge test stubs
- [ ] `tests/test_simulation.py` — extend with live graph memory integration stubs

*Existing test infrastructure (pytest, pytest-asyncio, conftest) already in place from prior phases.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LLM-generated decision narratives | GRAPH-02 (interview context) | Requires live Ollama + worker model | Run simulation, inspect Agent.decision_narrative in Neo4j Browser |
| Transaction count per round | GRAPH-01 (SC-4) | Requires Neo4j query log monitoring | Enable Neo4j query logging, run simulation, verify ≤10 transactions per round |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
