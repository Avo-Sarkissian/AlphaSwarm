# Phase 28: Simulation Replay - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the Q&A.

**Date:** 2026-04-12
**Phase:** 28-simulation-replay
**Mode:** discuss

## Areas Discussed

### Entry Point

| Question | Options Presented | Selected |
|----------|------------------|---------|
| How should the user trigger replay? | CLI only / TUI shortcut / Both | Both |

### Round Navigation

| Question | Options Presented | Selected |
|----------|------------------|---------|
| How do rounds advance during replay? | Manual step / Auto-advance / Both modes | Auto by default, configurable to manual |

### Data Loading

| Question | Options Presented | Selected |
|----------|------------------|---------|
| How to fetch cycle data from Neo4j? | New `read_full_cycle()` / Reuse per-round `read_*` / Hybrid | Hybrid (upfront signals, on-demand richer data) |

### TUI Approach

| Question | Options Presented | Selected |
|----------|------------------|---------|
| How does replay render in the TUI? | Reuse `AlphaSwarmApp` / Lightweight `ReplayScreen` / Separate `ReplayApp` | Reuse `AlphaSwarmApp` in replay mode |

## Corrections Made

None — all selections confirmed as-is.
