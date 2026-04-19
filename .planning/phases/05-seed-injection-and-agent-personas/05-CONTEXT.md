# Phase 5: Seed Injection and Agent Personas - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 delivers the seed injection pipeline and enriched agent personas. An orchestrator LLM (`qwen3.5:32b`) parses a natural-language seed rumor into a structured SeedEvent with named entities (companies, sectors, people) carrying relevance scores and per-entity sentiment. The 100 agent personas get refined system prompts with decision heuristics, information biases, and per-agent personality variation within brackets. A new CLI module provides an `inject` subcommand that runs end-to-end: load orchestrator model, parse rumor, persist SeedEvent + Entity nodes to Neo4j, unload model, and print a structured summary. No simulation rounds (Phase 6), no influence topology (Phase 8), no TUI (Phase 9).

</domain>

<decisions>
## Implementation Decisions

### SeedEvent Schema (SIM-01)
- **D-01:** SeedEvent is a frozen Pydantic model containing the raw rumor text alongside structured extraction output. Fields: `raw_rumor: str`, `entities: list[SeedEntity]`, `overall_sentiment: float` (aggregate).
- **D-02:** SeedEntity includes: `name: str`, `type: EntityType` (company/sector/person enum), `relevance: float` (0.0-1.0), `sentiment: float` (-1.0 to 1.0). Per-entity sentiment — each extracted entity gets its own sentiment score.
- **D-03:** SeedEvent entities are persisted as `(:Entity)` nodes in Neo4j linked to the Cycle via `(:Cycle)-[:MENTIONS]->(:Entity)`. Enables cross-cycle entity queries ("which rumors mentioned NVIDIA"). Entity nodes carry name, type, relevance, and sentiment properties.

### Orchestrator Prompting (SIM-01)
- **D-04:** Use `OllamaClient.chat()` with `format="json"` for seed parsing. Consistent with the worker agent pattern and leverages the existing multi-tier fallback infrastructure.
- **D-05:** Thinking mode enabled (`think=True`) for the orchestrator during entity extraction. Per Phase 2 CONTEXT.md decision: orchestrator uses "High Reasoning mode" for higher quality entity extraction and sentiment analysis.
- **D-06:** Dedicated `parse_seed_event()` function in `parsing.py` with the same 3-tier fallback pattern as `parse_agent_decision()`: JSON mode -> regex extraction -> error. Independently testable.
- **D-07:** Orchestrator model lifecycle managed within the seed injection pipeline. The pipeline loads `qwen3.5:32b` via OllamaModelManager, runs extraction, then unloads. Self-contained, aligns with INFRA-03 sequential loading contract.

### Persona Prompt Depth (SIM-02)
- **D-08:** Medium prompt depth — expand each bracket's system_prompt_template to ~150-250 words. Include: personality description, 2-3 specific decision heuristics per archetype, information biases, and response tone. Enough to drive diverse outputs without overwhelming the 4K worker context window.
- **D-09:** Per-agent variation within brackets. Each bracket has 3-5 predefined personality modifiers (e.g., cautious/aggressive/contrarian/momentum-driven) that are round-robin assigned to agents within the bracket. Deterministic, reproducible, testable.
- **D-10:** System prompts include explicit JSON output formatting instructions at the end. Each prompt ends with instructions specifying the expected output schema: `{signal, confidence, sentiment, rationale, cited_agents}`. Works alongside `format="json"` for maximum reliability.

### CLI Entry Point (Success Criterion 4)
- **D-11:** New `src/alphaswarm/cli.py` module with subcommand routing. `__main__.py` becomes a thin shim delegating to the CLI module. Cleaner separation for future subcommands.
- **D-12:** Seed rumor provided as a CLI argument string: `python -m alphaswarm inject "NVIDIA announces..."`. Simple, scriptable, single-command invocation.
- **D-13:** CLI outputs a structured summary after successful injection: cycle_id, extracted entities with relevance/sentiment, and overall sentiment. Formatted as a clean table or structured text confirming injection worked.

### Claude's Discretion
- SeedEvent Pydantic model field ordering and validation constraints
- EntityType enum values and naming
- Orchestrator system prompt wording for entity extraction
- Specific personality modifier pool for each bracket (cautious/aggressive/etc.)
- CLI argument parser library choice (argparse vs click vs typer)
- Neo4j Entity node index definitions
- Graph relationship naming (MENTIONS vs EXTRACTS vs CONTAINS)
- Output formatting details (table library, color, layout)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — SIM-01 (orchestrator entity extraction), SIM-02 (100 agents with distinct profiles), SIM-03 (structured decision output)
- `.planning/ROADMAP.md` — Phase 5 success criteria and dependencies

### Existing Implementation
- `src/alphaswarm/types.py` — AgentDecision, AgentPersona, BracketType, SignalType, SimulationPhase (all existing types)
- `src/alphaswarm/config.py` — DEFAULT_BRACKETS with system_prompt_templates (marked TODO for Phase 5), generate_personas(), persona_to_worker_config()
- `src/alphaswarm/ollama_client.py` — OllamaClient with chat()/generate() and backoff
- `src/alphaswarm/ollama_models.py` — OllamaModelManager for sequential model loading
- `src/alphaswarm/parsing.py` — parse_agent_decision() with 3-tier fallback (pattern to follow for parse_seed_event)
- `src/alphaswarm/graph.py` — GraphStateManager with create_cycle(), seed_agents(), write_decisions(), SCHEMA_STATEMENTS
- `src/alphaswarm/worker.py` — AgentWorker with infer(), WorkerPersonaConfig TypedDict
- `src/alphaswarm/app.py` — AppState container, create_app_state() factory
- `src/alphaswarm/__main__.py` — Current entry point (to be refactored into cli.py shim)
- `src/alphaswarm/errors.py` — Error hierarchy (pattern for new SeedInjectionError if needed)

### Prior Phase Context
- `.planning/phases/01-project-foundation/01-CONTEXT.md` — AppState container, frozen Pydantic models, 10 brackets
- `.planning/phases/02-ollama-integration/02-CONTEXT.md` — OllamaClient contracts, sequential model loading, multi-tier parse fallback, model tags (qwen3.5:32b orchestrator, qwen3.5:7b worker)
- `.planning/phases/03-resource-governance/03-CONTEXT.md` — Governor metrics, batch dispatch patterns
- `.planning/phases/04-neo4j-graph-state/04-CONTEXT.md` — Graph schema (Decision nodes, CITED relationships), UNWIND batch writes, session-per-method pattern

### Project Context
- `.planning/PROJECT.md` — Core value, constraints, LLM strategy, agent brackets
- `CLAUDE.md` — Project constraints (async, local-first, memory safety)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `parse_agent_decision()` in `parsing.py` — 3-tier fallback pattern to replicate for `parse_seed_event()`
- `OllamaClient.chat()` — ready to use with `format="json"` and `think=True` for orchestrator
- `OllamaModelManager` — handles sequential model loading/unloading lifecycle
- `GraphStateManager.create_cycle()` — already creates Cycle node with seed_rumor text
- `generate_personas()` in `config.py` — already generates 100 personas from brackets; needs extension for per-agent modifiers
- `SCHEMA_STATEMENTS` in `graph.py` — extend with Entity node constraints/indexes
- `AppState` + `create_app_state()` — container pattern for wiring new components

### Established Patterns
- Frozen Pydantic `BaseModel` for domain types (AgentPersona, AgentDecision, BracketConfig)
- `@asynccontextmanager` for resource lifecycle
- `structlog.get_logger(component="...")` for component-scoped logging
- `TYPE_CHECKING` guard for circular import avoidance
- `TypedDict` for hot-path configs, Pydantic for source-of-truth models
- Session-per-method in GraphStateManager
- UNWIND + MERGE for idempotent Neo4j writes

### Integration Points
- `config.py:DEFAULT_BRACKETS` — system_prompt_template strings to be refined (TODO markers)
- `config.py:generate_personas()` — extend to incorporate per-agent personality modifiers
- `graph.py:SCHEMA_STATEMENTS` — add Entity node constraint/index
- `graph.py:GraphStateManager` — add `write_seed_event()` method for Entity node creation
- `__main__.py` — refactor to delegate to new `cli.py` module
- `parsing.py` — add `parse_seed_event()` alongside existing `parse_agent_decision()`

</code_context>

<specifics>
## Specific Ideas

- SeedEntity type modeled after AgentDecision pattern: frozen Pydantic BaseModel with validation constraints on relevance (0.0-1.0) and sentiment (-1.0 to 1.0)
- EntityType enum: COMPANY, SECTOR, PERSON (may add more later but start minimal)
- Personality modifier pool example for Quants: ["conservative quantitative analyst", "aggressive statistical arbitrageur", "risk-averse factor modeler", "momentum-focused data scientist"]
- CLI output example: a table showing extracted entities with columns: Name | Type | Relevance | Sentiment
- The existing `create_cycle()` already stores raw rumor on the Cycle node — SeedEvent adds structured entity extraction on top

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-seed-injection-and-agent-personas*
*Context gathered: 2026-03-25*
