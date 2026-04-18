---
phase: 37
slug: isolation-foundation-provider-scaffolding
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 37 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 37-01-01 | 01 | 1 | ISOL-01 | — | Frozen dataclasses with extra=forbid reject unknown fields | unit | `uv run pytest tests/test_types_isolation.py -x -q` | ❌ W0 | ⬜ pending |
| 37-01-02 | 01 | 1 | ISOL-02 | — | Pydantic swarm-side types have zero holdings fields | unit | `uv run pytest tests/test_types_isolation.py -x -q` | ❌ W0 | ⬜ pending |
| 37-02-01 | 02 | 1 | ISOL-03 | — | importlinter contract rejects violation import | integration | `uv run lint-imports` | ❌ W0 | ⬜ pending |
| 37-02-02 | 02 | 1 | ISOL-03 | — | importlinter contract passes on clean tree | integration | `uv run lint-imports` | ❌ W0 | ⬜ pending |
| 37-03-01 | 03 | 1 | ISOL-04 | — | Canary test passes with sentinel fixtures | unit | `uv run pytest tests/test_holdings_isolation.py -x -q` | ❌ W0 | ⬜ pending |
| 37-04-01 | 04 | 2 | ISOL-05 | — | pytest-socket blocks outbound network calls | unit | `uv run pytest tests/test_network_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 37-05-01 | 05 | 2 | ISOL-06 | — | PII redaction processor strips holdings/portfolio/cost_basis keys | unit | `uv run pytest tests/test_pii_redaction.py -x -q` | ❌ W0 | ⬜ pending |
| 37-05-02 | 05 | 2 | ISOL-06 | — | Hypothesis fuzz test finds zero verbatim PII in log stream | property | `uv run pytest tests/test_pii_redaction.py -x -q` | ❌ W0 | ⬜ pending |
| 37-06-01 | 06 | 2 | ISOL-07 | — | structlog globally configured with PII processor | unit | `uv run pytest tests/test_pii_redaction.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_types_isolation.py` — stubs for ISOL-01, ISOL-02
- [ ] `tests/test_holdings_isolation.py` — canary stubs for ISOL-04
- [ ] `tests/test_network_gate.py` — stubs for ISOL-05
- [ ] `tests/test_pii_redaction.py` — stubs for ISOL-06, ISOL-07
- [ ] `tests/test_importlinter_contract.py` — stubs for ISOL-03
- [ ] `pytest-socket`, `import-linter`, `hypothesis` — added to dev dependencies

*All test files missing — Wave 0 must create them before implementation tasks begin.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| importlinter fails on intentional violation commit | ISOL-03 | Requires a deliberate bad commit to CI | Create a test branch with an illegal import, push, confirm CI fails |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
