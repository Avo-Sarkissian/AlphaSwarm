# Phase 26: Shock Injection Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-10
**Phase:** 26-shock-injection-core
**Mode:** discuss
**Areas analyzed:** Governor Suspend/Resume, Shock Queue Architecture, Agent Prompt Propagation, Neo4j Persistence, TUI Input Widget

## Assumptions Presented

### Governor Suspend/Resume
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add `suspend()`/`resume()` that only toggle `_resume_event` — no state-machine changes | Confident | `governor.py:203-205` (_resume_event is sole acquire gate), `governor.py:347-384` (state transitions are monitor-loop driven only) |

### Agent Prompt Propagation
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Compute `effective_message` in `simulation.py` and pass to `dispatch_wave(user_message=...)` — zero layer changes below | Confident | `batch_dispatcher.py:67-68`, `worker.py:87-92` (user_message flows through unchanged) |

### Shock Queue Architecture
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `asyncio.Queue(maxsize=1)` + `asyncio.Event` added to `StateStore`, awaited at inter-round gaps | Likely | `state.py:109` (_rationale_queue pattern), `simulation.py:833-853`, `simulation.py:974-978` (inter-round gaps) |

### Neo4j Persistence
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `ShockEvent` node + `(Cycle)-[:HAS_SHOCK]->(ShockEvent)` with session-per-method write | Likely | `graph.py:101-106` (session pattern), `graph.py:233-244` (Cycle node as root parent) |

### TUI Input Widget
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Inline `ShockInputBar` docked in `#bottom-row`, hidden by default | Likely | `tui.py:716-719` (#bottom-row), `tui.py:431-447` (RumorInputScreen), `tui.py:491-494` (InterviewScreen inline Input) |

## Corrections Made

### TUI Input Widget
- **Original assumption:** Inline `ShockInputBar` docked in `#bottom-row`, `display: none` by default — grid and telemetry stay visible while typing
- **User correction:** Overlay Screen (like InterviewScreen) — `push_screen(ShockInputScreen(...))` on shock window open
- **Reason:** Consistent with existing UX pattern — both seed rumor and shock entered via full-screen overlay

## No Corrections (locked as-is)
- Governor suspend/resume — Confident assumption confirmed
- Agent prompt propagation — Confident assumption confirmed
- Shock queue on StateStore — Recommended option selected
- Neo4j ShockEvent + HAS_SHOCK — Recommended option selected
