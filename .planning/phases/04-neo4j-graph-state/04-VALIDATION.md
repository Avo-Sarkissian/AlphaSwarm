---
phase: 4
slug: neo4j-graph-state
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `uv run pytest tests/test_graph_state.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds (includes Neo4j container startup) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_graph_state.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | INFRA-05 | integration | `uv run pytest tests/test_graph_state.py::test_schema_creation -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | INFRA-06 | integration | `uv run pytest tests/test_graph_state.py::test_batch_write -x` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | INFRA-06 | integration | `uv run pytest tests/test_graph_state.py::test_peer_reads -x` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | INFRA-05 | integration | `uv run pytest tests/test_graph_state.py::test_concurrent_sessions -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_graph_state.py` — stubs for INFRA-05, INFRA-06
- [ ] `tests/conftest.py` — Neo4j connection fixture (requires running Docker container)

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Docker container startup | INFRA-05 | Requires Docker daemon | `docker compose up -d` then verify `docker compose ps` shows healthy |
| Sub-5ms read performance | INFRA-05 | Timing-dependent | Run peer read benchmark and verify < 5ms with composite index |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
