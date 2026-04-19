# Phase 7: Rounds 2-3 Peer Influence and Consensus - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 7 adds Rounds 2-3 to the simulation pipeline, completing the 3-round consensus cascade. Each agent receives top-5 peer decisions from the prior round as context and re-evaluates their position. Round 3 produces final locked positions. Delivers: `run_simulation()` orchestrating all 3 rounds, peer context formatting, per-round reporting with shift analysis, SimulationPhase state transitions, and a `SimulationResult` container. No dynamic influence topology (Phase 8), no TUI (Phase 9). Peer ranking uses static `influence_weight_base` until Phase 8 wires citation-based dynamic edges.

</domain>

<decisions>
## Implementation Decisions

### Peer Context Formatting
- **D-01:** Structured summary format for peer_context string. Each of the top-5 peers rendered as: `[Bracket] SIGNAL (conf: X.XX)` followed by an 80-char truncated rationale snippet. ~250 tokens total for 5 peers. Balances information density with the worker's 4K context window.
- **D-02:** Rationale snippets truncated at 80 characters, consistent with Phase 6's `_sanitize_rationale()` pattern. Same sanitization applied (strip control chars, normalize whitespace).
- **D-03:** Peer context includes a header indicating which round's decisions are being shown (e.g., "Peer Decisions (Round 1)").

### Pipeline Architecture
- **D-04:** Single `run_simulation()` top-level async function orchestrating all 3 rounds. Calls existing `run_round1()` for the first round (preserving it as a standalone function), then handles Rounds 2-3 inline with the worker model staying loaded.
- **D-05:** Worker model reloaded once after `run_round1()` returns (since `run_round1()` unloads in its finally block). Worker stays loaded for both Rounds 2-3 — no reload between them. One cold load cost for preserving modularity.
- **D-06:** Governor monitoring spans Rounds 2-3 dispatch. `run_round1()` manages its own governor lifecycle; `run_simulation()` starts a fresh monitoring session for the Rounds 2-3 phase.
- **D-07:** SimulationPhase state machine transitions: IDLE → SEEDING → ROUND_1 → ROUND_2 → ROUND_3 → COMPLETE. Phase transitions logged via structlog but not persisted to a SharedStateStore (deferred until TUI needs it).
- **D-08:** `SimulationResult` frozen dataclass containing Round1Result + per-round agent_decisions + shift metrics. Single canonical result container for the full simulation.

### Peer Decision Reads
- **D-09:** For Round 2: read top-5 peer decisions from Round 1 for each agent via `read_peer_decisions(agent_id, cycle_id, round_num=1)`. For Round 3: same but `round_num=2`. Each agent gets personalized peer context (excluding self).
- **D-10:** Peer reads happen per-agent BEFORE dispatch, serialized into the peer_context string. The formatting function builds the context string, then `dispatch_wave()` receives it as the `peer_context` kwarg.

### Opinion Shift Detection
- **D-11:** Signal flips tracked between rounds: count agents who changed signal (BUY→SELL, SELL→HOLD, etc.) with a transition breakdown.
- **D-12:** Confidence delta computed per bracket: average confidence change between rounds. Reported alongside the bracket table after each round.
- **D-13:** Shift metrics computed by comparing Round N-1 and Round N agent_decisions. No Neo4j query needed — done in-memory from the result containers.

### CLI Output
- **D-14:** Per-round bracket tables printed as each round completes, reusing the `_print_round1_report()` pattern. Users see progressive output during the ~10 minute simulation.
- **D-15:** Shift analysis section added after Round 2 and Round 3 reports showing signal change counts and per-bracket confidence drift.
- **D-16:** Final "Simulation Complete" summary with total signal flips across rounds, convergence indicator, and final bracket consensus distribution.
- **D-17:** The existing `run` CLI subcommand evolves to run the full 3-round simulation (not just Round 1). `_handle_run()` calls `run_simulation()` instead of `run_round1()`.

### Claude's Discretion
- Internal helper function structure within `run_simulation()` (e.g., `_dispatch_round()`, `_format_peer_context()`, `_compute_shifts()`)
- Whether to parallelize peer reads across agents or serialize them (token budget vs Neo4j load)
- SimulationResult field naming and structure beyond the core round results
- Exact formatting of shift analysis output (column widths, alignment)
- How to handle the case where ALL 100 agents get the same top-5 peers (static ranking makes this likely — acceptable until Phase 8 dynamic topology)
- Whether run_round1() standalone mode needs a separate CLI flag or just works as before

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation (Primary)
- `src/alphaswarm/simulation.py` — `run_round1()` pipeline and `Round1Result` dataclass. Extend with `run_simulation()` and `SimulationResult`.
- `src/alphaswarm/graph.py` — `read_peer_decisions()` returns `PeerDecision(agent_id, bracket, signal, confidence, sentiment, rationale)` ranked by static `influence_weight_base`. Already supports round_num parameter.
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave()` with `peer_context: str | None` kwarg. Pass formatted peer string for Rounds 2-3.
- `src/alphaswarm/worker.py` — `AgentWorker.infer()` injects peer_context as second system message when not None. `WorkerPersonaConfig` TypedDict.
- `src/alphaswarm/cli.py` — `_handle_run()`, `_run_pipeline()`, `_print_round1_report()`, `_aggregate_brackets()`, `_sanitize_rationale()`. Extend for 3-round reporting.
- `src/alphaswarm/types.py` — `SimulationPhase` enum (IDLE, SEEDING, ROUND_1, ROUND_2, ROUND_3, COMPLETE), `AgentDecision`, `SignalType`, `AgentPersona`.
- `src/alphaswarm/config.py` — `persona_to_worker_config()`, `AppSettings`, `GovernorSettings`.
- `src/alphaswarm/governor.py` — `ResourceGovernor.start_monitoring()`, `stop_monitoring()`.
- `src/alphaswarm/ollama_models.py` — `OllamaModelManager.load_model()`, `unload_model()`, `ensure_clean_state()`.
- `src/alphaswarm/app.py` — `AppState`, `create_app_state()`.

### Requirements
- `.planning/REQUIREMENTS.md` — SIM-05 (Round 2 peer influence), SIM-06 (Round 3 final consensus lock)
- `.planning/ROADMAP.md` — Phase 7 success criteria (5 criteria including state machine transitions)

### Prior Phase Context
- `.planning/phases/06-round-1-standalone/06-CONTEXT.md` — Pipeline function pattern (D-106), async-safe CLI (D-02), raw rumor as user_message (D-04)
- `.planning/phases/04-neo4j-graph-state/04-CONTEXT.md` — read_peer_decisions uses static influence_weight_base (D-09), session-per-method pattern (D-07)
- `.planning/phases/03-resource-governance/03-CONTEXT.md` — Governor monitoring lifecycle, dispatch_wave failure tracking

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `run_round1()` in `simulation.py` — complete Round 1 pipeline, returns `Round1Result`. Called by `run_simulation()` for the first round.
- `dispatch_wave()` in `batch_dispatcher.py` — accepts `peer_context` kwarg, already wired for Rounds 2-3. Pass formatted string.
- `read_peer_decisions()` in `graph.py` — returns top-N `PeerDecision` objects. Ready to use for peer context assembly.
- `_print_round1_report()` / `_aggregate_brackets()` / `_sanitize_rationale()` in `cli.py` — report functions to reuse/extend for per-round output.
- `SimulationPhase` enum in `types.py` — ROUND_1/ROUND_2/ROUND_3/COMPLETE values already defined.
- `PeerDecision` dataclass in `graph.py` — agent_id, bracket, signal, confidence, sentiment, rationale fields.

### Established Patterns
- Nested try/finally for multi-resource cleanup (inner: model, outer: governor) — from `run_round1()`
- `_sanitize_rationale(text, max_len=80)` for rationale truncation
- `persona_to_worker_config()` for AgentPersona → WorkerPersonaConfig conversion
- structlog with component-scoped loggers
- Frozen dataclasses for result containers (`Round1Result`)

### Integration Points
- `simulation.py` — add `run_simulation()`, `SimulationResult`, `_format_peer_context()`, `_dispatch_round()`
- `cli.py:_run_pipeline()` — switch from `run_round1()` to `run_simulation()`
- `cli.py` — add `_print_round_report()` (generalized), `_print_shift_analysis()`, `_print_simulation_summary()`
- `graph.py:read_peer_decisions()` — called per-agent for Rounds 2-3 peer context assembly

</code_context>

<specifics>
## Specific Ideas

- Peer context format matches the mockup: numbered list with `[Bracket] SIGNAL (conf: X.XX)` and quoted rationale snippet
- Shift analysis shows signal change counts (BUY→SELL: N, etc.) and per-bracket average confidence delta
- Final summary includes convergence indicator: whether signal flips decreased between Round 2→3 vs Round 1→2
- `run_simulation()` calls `run_round1()` then reloads worker and handles Rounds 2-3 in a single governor monitoring session
- Per-round reports print progressively so the user sees results during the ~10 minute simulation runtime

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-rounds-2-3-peer-influence-and-consensus*
*Context gathered: 2026-03-26*
