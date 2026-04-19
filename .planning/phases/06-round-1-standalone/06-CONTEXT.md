# Phase 6: Round 1 Standalone - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 wires together existing infrastructure into a Round 1 simulation pipeline. A unified `run` CLI command takes a seed rumor, injects it (orchestrator model parse + Neo4j persist), loads the worker model, dispatches all 100 agents through `dispatch_wave()` with zero peer context, batch-writes decisions to Neo4j, and prints a bracket-level signal distribution with top-mover highlights. No peer influence (Phase 7), no dynamic topology (Phase 8), no TUI (Phase 9). This is the headless engine's first end-to-end simulation pass.

</domain>

<decisions>
## Implementation Decisions

### Invocation Flow
- **D-01:** Unified `run` CLI subcommand — `python -m alphaswarm run "rumor text"` executes the full pipeline: inject seed → unload orchestrator → load worker → dispatch wave → persist decisions → report results. One command, end-to-end.
- **D-02:** The `run` command reuses the existing `inject_seed()` pipeline internally. No separate `round1` subcommand — keep CLI surface minimal for now.
- **D-03:** Sequential model lifecycle within the pipeline: orchestrator loads for seed parsing, unloads, then worker loads for agent inference. Follows INFRA-03 sequential loading contract.

### Agent Prompt Construction
- **D-04:** Raw rumor only as the user message for Round 1. Agents receive the natural-language rumor text, NOT the structured SeedEvent entities/sentiment. Each persona's system prompt already encodes archetype-specific biases and heuristics — raw rumor forces diverse interpretation.
- **D-05:** Message format: system prompt (persona-specific) + user message (raw rumor). No peer_context in Round 1 (peer_context=None passed to dispatch_wave).

### Result Reporting
- **D-06:** Bracket summary table + top movers output. Bracket table shows signal counts (BUY/SELL/HOLD) and average confidence per bracket. Below that, "Notable Decisions" section highlights top 5 highest-confidence agents with signal, confidence, and rationale snippet.
- **D-07:** Report includes header with total agent count and success/failure breakdown (e.g., "100/100 agents" or "98/100 agents, 2 PARSE_ERROR").

### Simulation State
- **D-08:** Neo4j-only state tracking for Round 1. Completion is implicit: 100 Decision nodes with (cycle_id, round=1) means done. No SharedStateStore phase transitions yet — Phase 7 will introduce the state machine for the 3-round cascade.
- **D-09:** SimulationPhase enum already exists with ROUND_1/COMPLETE values — available for Phase 7 when needed, not wired in Phase 6.

### Claude's Discretion
- Internal pipeline function structure (single `run_round1()` or composed from smaller functions)
- Worker model loading strategy within the pipeline (reuse model_manager patterns from seed.py)
- Bracket table formatting details (column widths, alignment)
- How to select "top 5 by confidence" — simple sort on AgentDecision.confidence
- Error handling for partial wave failures (PARSE_ERROR agents still counted in bracket totals)
- Whether to print progress indicators during the wave dispatch

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation (Primary)
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave()` with TaskGroup, jitter, failure tracking. THE core dispatch function for Round 1.
- `src/alphaswarm/worker.py` — `agent_worker()` context manager, `AgentWorker.infer()` with peer_context=None support
- `src/alphaswarm/seed.py` — `inject_seed()` pipeline (orchestrator load → parse → persist → unload). Reuse within `run` command.
- `src/alphaswarm/cli.py` — argparse subparsers pattern, `_handle_inject()` as template for `_handle_run()`
- `src/alphaswarm/graph.py` — `GraphStateManager.write_decisions()` for batch persist, `read_peer_decisions()` (not needed in Phase 6)
- `src/alphaswarm/config.py` — `persona_to_worker_config()` for converting AgentPersona → WorkerPersonaConfig
- `src/alphaswarm/types.py` — `AgentDecision`, `SignalType`, `SimulationPhase`, `BracketType`
- `src/alphaswarm/app.py` — `AppState` container, `create_app_state()` factory
- `src/alphaswarm/governor.py` — `ResourceGovernor` for concurrency slot management
- `src/alphaswarm/ollama_models.py` — `OllamaModelManager` for sequential model loading

### Requirements
- `.planning/REQUIREMENTS.md` — SIM-04 (Round 1 independent processing)
- `.planning/ROADMAP.md` — Phase 6 success criteria and dependencies

### Prior Phase Context
- `.planning/phases/03-resource-governance/03-CONTEXT.md` — BatchDispatcher decisions (D-04 through D-06: wave scope, shrink policy, no batch retry)
- `.planning/phases/05-seed-injection-and-agent-personas/05-CONTEXT.md` — Seed injection pipeline decisions, persona prompt depth, CLI subcommand pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dispatch_wave()` in `batch_dispatcher.py` — fully implemented TaskGroup dispatch with jitter, governor integration, and failure tracking. Accepts `peer_context=None` for Round 1.
- `inject_seed()` in `seed.py` — complete seed injection pipeline returning (cycle_id, ParsedSeedResult). Self-contained model lifecycle.
- `_handle_inject()` in `cli.py` — template for the `_handle_run()` function: AppState setup, ensure_schema(), pipeline call, summary print, cleanup.
- `persona_to_worker_config()` in `config.py` — converts frozen AgentPersona to lightweight WorkerPersonaConfig TypedDict for dispatch.
- `write_decisions()` in `graph.py` — UNWIND batch write accepting list[tuple[str, AgentDecision]] with cycle_id and round_num.

### Established Patterns
- argparse subparsers for CLI routing (cli.py)
- `asyncio.run()` wrapping async handlers in CLI (cli.py)
- `create_app_state()` with `with_ollama=True, with_neo4j=True` for full-stack setup
- Sequential model lifecycle: load → use → unload in try/finally (seed.py)
- structlog with component-scoped loggers
- `TYPE_CHECKING` guard for circular import avoidance

### Integration Points
- `cli.py:main()` — add `run` subparser alongside existing `inject`
- `app.py:AppState` — provides ollama_client, model_manager, graph_manager, governor
- `config.py:generate_personas()` + `persona_to_worker_config()` — persona pipeline
- `graph.py:write_decisions()` — accepts (agent_id, AgentDecision) tuples with cycle_id and round_num

</code_context>

<specifics>
## Specific Ideas

- The `run` command output should match the preview mockup: header with agent count, bracket table with BUY/SELL/HOLD/Avg Conf columns, then "Notable Decisions" with top 5 by confidence showing rationale snippets
- PARSE_ERROR agents should be counted separately in the header (e.g., "98/100 agents, 2 failed") and excluded from bracket signal counts
- The pipeline is: inject_seed() → model_manager.unload() → model_manager.load(worker) → dispatch_wave() → write_decisions() → print report → model_manager.unload(worker)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-round-1-standalone*
*Context gathered: 2026-03-26*
