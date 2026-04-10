# Phase 26: Shock Injection Core - Context

**Gathered:** 2026-04-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Add governor suspend/resume, an inter-round shock queue, agent prompt propagation, and Neo4j persistence for ShockEvent nodes — so users can inject a breaking event between simulation rounds via a TUI overlay screen and see all 100 agents react to it in the next round. Shock analysis and reporting (before/after comparison) is Phase 27, not this phase.

</domain>

<decisions>
## Implementation Decisions

### Governor Suspend/Resume
- **D-01:** Add `suspend()` and `resume()` methods to `ResourceGovernor` that only clear/set `_resume_event` — no state-machine transitions and no interaction with the monitoring loop. The monitoring loop continues running throughout the shock pause.
- **D-02:** `_resume_event.clear()` in `suspend()` blocks all new `acquire()` calls; `_resume_event.set()` in `resume()` unblocks them. This is the minimal intervention that prevents false THROTTLED/PAUSED states.
- **D-03:** Do NOT call `stop_monitoring()` / `start_monitoring()` between rounds for the shock pause — that pattern is too destructive (drains pool, resets state to RUNNING, risks immediate false THROTTLED on restart).

### Shock Queue Architecture
- **D-04:** Add `asyncio.Queue(maxsize=1)` and `asyncio.Event` (shock window flag) to `StateStore` — consistent with the existing `_rationale_queue` pattern at `state.py:109`.
- **D-05:** `run_simulation()` suspends the governor at each inter-round gap, sets the shock-window event on StateStore (signaling TUI to show the overlay), then `await`s the queue. On receipt, resumes the governor and clears the shock-window flag.
- **D-06:** The TUI's shock overlay submits text by putting it onto the StateStore queue — same unidirectional StateStore-as-bridge pattern, no second inter-task channel.
- **D-07:** The shock window is optional per-round — if the user dismisses the overlay without submitting, simulation continues with no shock for that round (queue message = `None` or empty string).

### Agent Prompt Propagation
- **D-08:** In `simulation.py`, after reading the shock from the queue, compute `effective_message = f"{rumor}\n\n[BREAKING] {shock_text}"` and pass it to `dispatch_wave(user_message=effective_message, ...)` for the shocked round.
- **D-09:** No changes to `AgentWorker`, `dispatch_wave`, or `_safe_agent_inference` — shock travels through the existing `user_message` parameter chain unchanged (`batch_dispatcher.py:67-68`, `worker.py:87-92`).
- **D-10:** If no shock was submitted (user dismissed), pass bare `rumor` as usual — zero behavioral change for unshocked rounds.

### Neo4j Persistence
- **D-11:** Create a new `ShockEvent` node label with properties: `{shock_id, cycle_id, shock_text, injected_before_round, created_at}`.
- **D-12:** Relationship: `(c:Cycle)-[:HAS_SHOCK]->(se:ShockEvent)` — Cycle is the natural parent (already exists as simulation root node).
- **D-13:** Write uses the existing session-per-method pattern in `GraphStateManager` (`graph.py:101-106`). Called from `run_simulation()` after shock text received but before the shocked round's `dispatch_wave`.
- **D-14:** No `PRECEDES` edge to `Decision` nodes in this phase — that traversal is for Phase 27 analysis. Keep schema minimal for Phase 26.

### TUI Shock Input
- **D-15:** Implement as a new `ShockInputScreen` overlay (pushed via `push_screen()`, same pattern as `InterviewScreen` at `tui.py:779-787`), not an inline docked widget.
- **D-16:** The `_poll_snapshot()` 200ms timer detects the shock-window event on StateStore and calls `self.push_screen(ShockInputScreen(...))`. On dismiss, the screen's return value (shock text or `None`) is put onto the StateStore queue.
- **D-17:** `ShockInputScreen` mirrors `RumorInputScreen` structure (`tui.py:385-450`): single `Input` widget, submit on Enter, dismiss with the text. Header label distinguishes it ("Inject Breaking Event").

### Claude's Discretion
- Exact `shock_id` generation strategy (UUID4 is fine)
- Whether to add a Neo4j index on `ShockEvent.cycle_id` (consistent with schema conventions but not strictly required for 1-2 shocks per cycle)
- Placeholder label text in `ShockInputScreen`
- Whether Round 1 can be shocked (likely not — shock only applies to Rounds 2 and 3 since there's no "previous round" to react against)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Governor internals
- `src/alphaswarm/governor.py` — Full file. Focus on `_resume_event` (line ~203-205), `_monitor_loop` state transitions (line ~347-384), `stop_monitoring()` (line ~263-272), and the existing `acquire()` gate pattern.

### Simulation round orchestration
- `src/alphaswarm/simulation.py` — Full file. Focus on `run_simulation()`, the inter-round gaps between `on_round_complete` callback and the next `set_phase()` call (line ~833-853 for R1→R2, line ~974-978 for R2→R3), and how `dispatch_wave(user_message=rumor)` is called per round.

### StateStore (shared bridge)
- `src/alphaswarm/state.py` — Full file. Focus on `_rationale_queue` (line ~109) as the pattern for adding `asyncio.Queue` + `asyncio.Event` for shock.

### TUI overlay pattern
- `src/alphaswarm/tui.py` — Focus on `RumorInputScreen` (line ~385-450) for the ShockInputScreen template, `InterviewScreen` push pattern (line ~779-787) for how overlay screens are invoked, and `_poll_snapshot()` (line ~696) as the detection point for shock-window state.

### Neo4j schema and write patterns
- `src/alphaswarm/graph.py` — Focus on `SCHEMA_STATEMENTS` (line ~60-70) for index conventions, `Cycle` node creation (line ~233-244) for the HAS_SHOCK parent, and `session-per-method` write pattern (line ~101-106).

### Batch dispatch (for prompt propagation)
- `src/alphaswarm/batch_dispatcher.py` line ~67-68 — `user_message` passthrough to `worker.infer()`
- `src/alphaswarm/worker.py` line ~87-92 — final message list assembly (system + optional peer context + user message)

### Requirements
- `.planning/REQUIREMENTS.md` — SHOCK-01, SHOCK-02, SHOCK-03 (not yet formally defined — Phase 26 execution should create these entries)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ResourceGovernor._resume_event`: already the sole gate on `acquire()` — `suspend()`/`resume()` only need to call `.clear()` / `.set()` on this existing event
- `StateStore._rationale_queue` (`state.py:109`): exact pattern to copy for shock queue — bounded asyncio.Queue already proven for TUI↔simulation communication
- `RumorInputScreen` (`tui.py:385-450`): copy-paste template for `ShockInputScreen` — single Input, on_input_submitted → dismiss(value)
- `InterviewScreen` push pattern (`tui.py:779-787`): how to push a screen from the app and receive its dismiss value
- `GraphStateManager` session-per-method pattern (`graph.py:101-106`): standard for all new write methods — new `write_shock_event()` follows this exactly

### Established Patterns
- All Neo4j writes use `CREATE` (not `MERGE`) for per-round snapshot nodes — ShockEvent follows the same
- `dispatch_wave(user_message=rumor, ...)` is the single injection point for all 100 agents — changing one variable at the call site in `simulation.py` propagates to all agents with zero other changes
- `_poll_snapshot()` at 200ms is the established mechanism for StateStore → TUI reactivity; shock-window detection belongs here

### Integration Points
- `governor.py`: add `suspend()` / `resume()` methods
- `state.py`: add `_shock_queue: asyncio.Queue[str | None]` and `_shock_window: asyncio.Event` with accessor methods
- `simulation.py`: at each inter-round gap, call `governor.suspend()`, set shock window, await queue, apply shock to `dispatch_wave`, call `governor.resume()`
- `graph.py`: add `write_shock_event()` method and `ShockEvent` index to `SCHEMA_STATEMENTS`
- `tui.py`: add `ShockInputScreen` class, update `_poll_snapshot()` to detect shock-window and push the screen

</code_context>

<specifics>
## Specific Ideas

- The overlay screen approach mirrors the seed rumor entry flow exactly — consistent UX: both rumor and shock are entered via full-screen overlay, dismissed with Enter
- Governor `suspend()`/`resume()` must be the first task delivered (per STATE.md note) — all other shock mechanics depend on it being safe to pause between rounds

</specifics>

<deferred>
## Deferred Ideas

- `(ShockEvent)-[:PRECEDES]->(Decision)` relationship — useful for Phase 27 shock impact traversal but explicitly deferred from Phase 26 to keep the schema minimal
- Multi-shock support (more than one shock per cycle) — the node-per-shock schema supports this structurally, but the queue is maxsize=1 for Phase 26; multi-shock is a Phase 27+ concern
- Shocking Round 1 — likely not meaningful (no peer context to contrast against); Phase 27 analysis will confirm whether to enable it

</deferred>

---

*Phase: 26-shock-injection-core*
*Context gathered: 2026-04-10*
