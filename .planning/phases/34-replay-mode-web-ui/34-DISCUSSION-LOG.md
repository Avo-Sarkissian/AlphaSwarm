# Phase 34: Replay Mode Web UI - Discussion Log (Discuss Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-14
**Phase:** 34-replay-mode-web-ui
**Mode:** discuss
**Areas analyzed:** Cycle Picker, Replay Controls, Round Stepping, REPLAY Badge

## Gray Areas Presented

### Cycle Picker
| Assumption / Option | Selected | Evidence |
|--------------------|----------|----------|
| Modal overlay — focused dialog, no ControlBar clutter | ✓ YES | User confirmed recommended |
| Inline ControlBar dropdown | — | Not selected |

### Replay Controls Layout
| Assumption / Option | Selected | Evidence |
|--------------------|----------|----------|
| Replace seed area — same single-row footprint, swap content | ✓ YES | User confirmed recommended |
| Keep seed, add second row below | — | Not selected |

### Round Stepping
| Assumption / Option | Selected | Evidence |
|--------------------|----------|----------|
| Manual only — deliberate Next button, stays at Round 3/3 | ✓ YES | User confirmed recommended |
| Auto-advance with 2s interval toggle | — | Not selected |

### REPLAY Badge Placement
| Assumption / Option | Selected | Evidence |
|--------------------|----------|----------|
| Inside ControlBar as leftmost element of replay strip | ✓ YES | User confirmed recommended |
| Floating overlay badge anchored to force graph canvas | — | Not selected |

## Corrections Made

No corrections — all recommended options confirmed.

## Codebase Context Used

- `ReplayStore` fully built in `state.py:246` — constructor accepts `read_full_cycle_signals()` output directly
- `read_full_cycle_signals()` and `read_completed_cycles()` live in `graph.py:1779+`
- `/api/replay/cycles` endpoint is already live (not a stub); only `replay_start` and `replay_advance` need real logic
- `ControlBar.vue` already has `'replay': 'Replay'` in `phaseLabel` map — replay phase is known
- `AgentSidebar` and force graph node-click require zero changes — confirmed out of scope for this phase
- STATE.md blocker noted: `read_full_cycle_signals` may need performance profiling for 600+ node cycles
