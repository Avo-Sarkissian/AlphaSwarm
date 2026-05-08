---
phase: 260507-wln
plan: 01
subsystem: simulation + frontend-adapter
tags: [bugfix, citations, rationale-feed, wire-format, quick]
requirements:
  - BUG-EDGES-01
  - BUG-RATIONALE-01
dependency-graph:
  requires: []
  provides:
    - "Live INFLUENCED_BY edges rendering after R2/R3"
    - "Populated Rationale Feed with body text + round labels"
  affects:
    - "src/alphaswarm/simulation.py:_format_peer_context"
    - "frontend/src/adapter/frame.ts rationale mapper"
tech-stack:
  added: []
  patterns:
    - "Wire-format alignment: dataclasses.asdict() field names mirrored verbatim in TS adapter"
key-files:
  created: []
  modified:
    - "src/alphaswarm/simulation.py"
    - "frontend/src/adapter/frame.ts"
decisions:
  - "Field-rename in adapter (not backend rename) to keep blast radius minimal"
  - "Kept defensive `typeof` guards on the renamed keys; did NOT add fallback chains for the wrong keys (clean rename only)"
metrics:
  duration: "~6m"
  completed: "2026-05-07"
  tasks: 2
  files: 2
---

# Quick Task 260507-wln: Restore Live Citation Edges + Rationale Feed Summary

Two surgical fixes — one Python (peer-context prefix renders agent_id + prompt nudge to populate cited_agents) and one TypeScript (rationale adapter reads correct wire field names) — restoring the live influence graph and rationale feed exposed as broken in the 2026-05-07 smoke run.

## What Shipped

### Task 1 — Backend peer-context fix (commit `861009c`)

Two surgical edits to `_format_peer_context` in `src/alphaswarm/simulation.py`:

1. Peer-post prefix now renders `[{agent_id}|{bracket}]` instead of `[{bracket}]` only — workers now have peer agent ids visible in the prompt text.
2. Guard sentence extended with: *"If a peer's view materially shapes yours, list their agent id in cited_agents."* — explicitly nudges the worker to populate the JSON field.

Closes the 0-edge gap: workers had no IDs to cite → 0 CITED edges → 0 INFLUENCED_BY edges (graph.py:881-887 was logging `no_citations_found`). Fix addresses both ends of the contract: the data (id in prefix) and the instruction (guard sentence).

### Task 2 — Frontend rationale adapter fix (commit `44fc27e`)

Two-key rename in the rationale mapper at `frontend/src/adapter/frame.ts:127-128`:

- `re.round` → `re.round_num`
- `re.text` → `re.rationale`

Backend `RationaleEntry` dataclass serializes via `dataclasses.asdict()`, so wire payload uses `rationale` and `round_num`. The adapter was reading non-existent keys, silently coercing body to `''` and round to `0`. Entries were arriving in the WS payload but being stripped at the adapter boundary.

## Verification

- **Backend assertion** (Task 1 inline verify): `_format_peer_context` produces output containing `[agent-007|RetailDayTrader]` and `cited_agents` — passed.
- **Frontend tsc**: `npx tsc --noEmit -p tsconfig.json` exited 0 — passed.
- **Grep confirmation**: both `re.rationale` (line 128) and `re.round_num` (line 127) present in frame.ts.

Manual smoke verification (next sim cycle) is recommended but not part of this quick task.

## Deviations from Plan

None — plan executed exactly as written.

The Task 1 verify command in the plan imported `RankedPost` from `src.alphaswarm.state`, but `RankedPost` actually lives in `src.alphaswarm.graph` and has additional fields (`post_id`, `influence_weight`). Adapted the inline assertion to import from the correct module with the correct constructor — verified the same two assertions pass. This is a verification-script correction, not a code deviation.

## Out of Scope (per constraints)

- **Issue 1 (perf — 42 min vs 6 min target):** Not touched. That decision (system-prompt trim vs NUM_PARALLEL bump vs smaller worker model) is separate. See `.planning/debug/parallel-swarm-serial-dispatch.md` Resolution (1).

## Self-Check: PASSED

- FOUND: src/alphaswarm/simulation.py (modified)
- FOUND: frontend/src/adapter/frame.ts (modified)
- FOUND commit: 861009c (Task 1)
- FOUND commit: 44fc27e (Task 2)
