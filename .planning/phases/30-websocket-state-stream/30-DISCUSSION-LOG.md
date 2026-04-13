> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-12
**Phase:** 30-websocket-state-stream
**Mode:** discuss
**Areas discussed:** Rationale entries in stream, IDLE-phase broadcasting, Payload completeness

## Gray Areas Presented

| Area | Options presented | User choice |
|------|------------------|-------------|
| Rationale entries in stream | Yes — include rationales / No — state stream only | Yes — include rationales |
| IDLE-phase broadcasting | Always-on / Active simulation only | Always-on |
| Payload completeness | Full StateSnapshot / Lean subset | Full StateSnapshot |

## Discussion Detail

### Rationale entries in stream
- **Options:** Include `drain_rationales(5)` per tick in broadcast JSON vs. keep stream signal/phase/bracket only
- **Decision:** Include — broadcaster owns rationale drain. Phase 33 rationale sidebar reads from state stream (consistent with Phase 29 D-06 intent and v5.0 web-first direction).

### IDLE-phase broadcasting
- **Options:** Always-on asyncio.Task in lifespan vs. start/stop tied to SimulationManager
- **Decision:** Always-on — IDLE snapshots cheap, Vue frontend gets a stable "waiting" state, no complex lifecycle wiring.

### Payload completeness
- **Options:** Full StateSnapshot (all fields) vs. lean subset (phase + agent_states only)
- **Decision:** Full — Phases 31–33 panels need agent_states, bracket_summaries, governor_metrics, tps, rationale_entries from the stream. Avoids REST polling in monitoring panels.

## Corrections Made

No corrections — all recommended options selected.
