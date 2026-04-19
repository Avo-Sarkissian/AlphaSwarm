---
phase: 40
slug: simulation-context-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
---

# Phase 40 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24+ (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_simulation.py tests/test_worker.py tests/test_batch_dispatcher.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds (quick), ~90 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_simulation.py tests/test_worker.py tests/test_batch_dispatcher.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite green + `uv run lint-imports` + `uv run mypy src`
- **Max feedback latency:** ~30 seconds (quick), ~90 seconds (full)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 40-01-01 | 01 | 1 | SIM-04 | — | market_context flows through dispatch_wave → worker.infer | unit | `uv run pytest tests/test_batch_dispatcher.py::test_dispatch_wave_forwards_market_context -x` | ❌ W0 | ⬜ pending |
| 40-01-02 | 01 | 1 | SIM-04 | — | AgentWorker.infer injects market_context as system message before user message | unit | `uv run pytest tests/test_worker.py::test_infer_with_market_context -x` | ❌ W0 | ⬜ pending |
| 40-01-03 | 01 | 1 | SIM-04 | — | Market context injection is Round 1 only | unit | `uv run pytest tests/test_simulation.py::test_market_context_round1_only -x` | ❌ W0 | ⬜ pending |
| 40-02-01 | 02 | 1 | INGEST-03 | T-38-01 | run_simulation assembles ContextPacket from providers after inject_seed | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_assembles_context_packet -x` | ❌ W0 | ⬜ pending |
| 40-02-02 | 02 | 1 | INGEST-03 | — | ContextPacket assembly emits context_assembly_skipped when providers=None | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_skips_context_when_providers_missing -x` | ❌ W0 | ⬜ pending |
| 40-02-03 | 02 | 1 | INGEST-03 | — | ContextPacket formatter drops fetch_failed slices silently | unit | `uv run pytest tests/test_simulation.py::test_format_market_context_drops_fetch_failed -x` | ❌ W0 | ⬜ pending |
| 40-02-04 | 02 | 1 | SIM-04 | — | run_simulation accepts market_provider=None, news_provider=None; backward-compatible | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_backward_compatible -x` | ❌ W0 | ⬜ pending |
| 40-03-01 | 03 | 2 | INGEST-03 | ISOL-04 | ContextPacket logged without PII redaction kicking in | unit | `uv run pytest tests/test_logging.py::test_context_packet_not_redacted -x` | ❌ W0 | ⬜ pending |
| 40-03-02 | 03 | 2 | — | — | lifespan constructs providers; sim_manager forwards them | integration | `uv run pytest tests/test_web.py::test_lifespan_wires_providers -x` | ❌ W0 | ⬜ pending |
| 40-03-03 | 03 | 2 | — | — | cli._run_pipeline constructs providers before calling run_simulation | unit | `uv run pytest tests/test_cli.py::test_run_pipeline_constructs_providers -x` | ❌ W0 | ⬜ pending |
| 40-03-04a | 03 | 2 | INGEST-03, SIM-04 | — | Forwarding: run_simulation→run_round1 receives formatted market_context string from fake providers | integration (no network) | `uv run pytest tests/test_simulation.py::test_run_simulation_forwards_market_context_to_run_round1 -x` | ❌ W0 | ⬜ pending |
| 40-03-04b | 03 | 2 | INGEST-03, SIM-04 | — | Dispatch-depth: run_round1→dispatch_wave→AgentWorker.infer messages contain market_context system message at correct index | integration (no network) | `uv run pytest tests/test_simulation.py::test_run_simulation_through_dispatch_wave -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_simulation.py` — add Phase 40 section: `_format_market_context` tests, `run_simulation` provider wiring tests, fetch_failed filter test, round1-only guard test, backward-compat test, end-to-end test
- [ ] `tests/test_worker.py` — add `test_infer_with_market_context` mirroring `test_infer_with_peer_context` (worker.py:154-167)
- [ ] `tests/test_batch_dispatcher.py` — add `test_dispatch_wave_forwards_market_context` mirroring the peer_context forward test
- [ ] `tests/test_logging.py` — add canary test asserting `market`/`news` keys are NOT redacted by PII processor
- [ ] `tests/test_web.py` — add lifespan test asserting `app.state.market_provider` and `app.state.news_provider` are constructed
- [ ] `tests/test_cli.py` — add test asserting `_run_pipeline` constructs both providers before calling `run_simulation`

No new test framework install needed — pytest-asyncio, pytest-socket, conftest fixtures already in place.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (quick), < 90s (full)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
