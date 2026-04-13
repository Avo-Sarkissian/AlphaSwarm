---
phase: 30
slug: websocket-state-stream
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `uv run pytest tests/test_web.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_web.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 30-01-01 | 01 | 0 | BE-04 | — | N/A | unit | `uv run pytest tests/test_web.py::test_snapshot_to_json -x` | ❌ W0 | ⬜ pending |
| 30-01-02 | 01 | 0 | BE-04 | — | N/A | unit | `uv run pytest tests/test_web.py::test_broadcaster_cancellation -x` | ❌ W0 | ⬜ pending |
| 30-01-03 | 01 | 1 | BE-04 (SC-1) | — | N/A | integration | `uv run pytest tests/test_web.py::test_ws_state_receives_snapshot -x` | ❌ W0 | ⬜ pending |
| 30-01-04 | 01 | 1 | BE-04 (SC-2) | — | N/A | unit | `uv run pytest tests/test_web.py::test_websocket_queue_isolation -x` | ✅ Phase 29 | ⬜ pending |
| 30-01-05 | 01 | 1 | BE-04 (SC-3) | — | N/A | unit | `uv run pytest tests/test_web.py::test_ws_state_disconnect_cleanup -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web.py::test_snapshot_to_json` — unit test for snapshot serialization helper (BE-04)
- [ ] `tests/test_web.py::test_broadcaster_cancellation` — unit test for lifespan teardown task cancellation (BE-04)
- [ ] `tests/test_web.py::test_ws_state_receives_snapshot` — integration: WebSocket stream produces JSON at ~200ms (SC-1)
- [ ] `tests/test_web.py::test_ws_state_disconnect_cleanup` — integration: clean disconnect removes writer task (SC-3)
- [ ] `tests/test_web.py` `_make_test_app()` — update to include `ws_router` so WebSocket tests work

*Note: `test_websocket_queue_isolation` (SC-2) already exists from Phase 29. Verify it still passes after Phase 30 changes.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| wscat stream at ~200ms intervals | BE-04 (SC-1) | Real-time timing validation | `wscat -c ws://localhost:8000/ws/state` during active simulation; observe ~200ms cadence |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
