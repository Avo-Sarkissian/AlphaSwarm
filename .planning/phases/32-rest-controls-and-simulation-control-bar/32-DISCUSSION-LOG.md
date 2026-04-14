# Phase 32: REST Controls and Simulation Control Bar - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the Q&A.

**Date:** 2026-04-14
**Phase:** 32-rest-controls-and-simulation-control-bar
**Mode:** discuss
**Areas discussed:** Control bar layout, Simulation wiring, Shock injection semantics, Replay endpoint depth

---

## Areas Discussed

### Control Bar Layout

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| Where does the control bar live? | Persistent top strip / Overlay on empty state only / Bottom HUD strip | Persistent top strip |
| What controls appear in the active state? | Stop + phase label + Inject Shock / Phase label + Inject Shock no Stop / Phase label only | Stop + phase label + Inject Shock |
| How should the seed input behave when Start is clicked? | Input + button both disabled / Button disabled, input stays editable | Input + button both disabled |

### Simulation Wiring

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| How should SimulationManager fire run_simulation()? | asyncio.create_task inside the lock / Release lock fire task re-acquire is_running | asyncio.create_task inside the lock |
| Does Phase 32 implement a real stop()? | Yes — cancel the background task / No — stub it | Yes — cancel the background task |

### Shock Injection Semantics

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| What IS a shock — what does the backend do with shock text? | Acknowledge and queue it / Inject into active round immediately / Pure contract stub | Acknowledge and queue it |
| What does the shock injection drawer look like? | Slide-down panel under top bar / Modal dialog / Inline in the top bar | Slide-down panel under top bar |

### Replay Endpoint Depth

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| How deep should replay endpoints go? | Real GET /cycles + contract stubs for start/advance / All three fully implemented / All three stubs | Real GET /cycles + contract stubs for start/advance |

---

## Corrections Made

No corrections — all recommended defaults accepted.

---

*Discussion mode: interactive*
*All gray areas confirmed on first pass*
