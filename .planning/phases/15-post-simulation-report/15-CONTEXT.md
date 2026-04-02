# Phase 15: Post-Simulation Report - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 15 adds a ReACT-style report agent that autonomously queries Neo4j post-simulation and generates a structured 8-section market analysis report as exportable markdown. Delivered as a CLI `report` subcommand (`alphaswarm report --cycle <cycle_id>`). The TUI displays the output file path via a sentinel file mechanism. Report uses the orchestrator model — never runs concurrently with agent interviews (worker model). No new TUI panels. No changes to simulation flow. No interactive report editing.

</domain>

<decisions>
## Implementation Decisions

### ReACT Tool Dispatch
- **D-01:** Structured `ACTION`/`INPUT` block format. LLM outputs a literal text block containing `ACTION: <tool_name>` on one line followed by `INPUT: <json>` on the next. Parsed by line-scan or regex — no JSON extraction from prose. Predictable, testable, robust against LLM verbosity.
- **D-02:** `FINAL_ANSWER` is a reserved tool name. When the LLM emits `ACTION: FINAL_ANSWER`, the loop terminates immediately and collected observations are passed to the report renderer. No DONE keyword scanning in THOUGHT text.
- **D-03:** Hard iteration cap of 8-10 (from ROADMAP success criteria). If the cap is reached without a `FINAL_ANSWER`, the loop exits and renders with whatever observations were collected. Duplicate call detection (same tool + same input twice) counts as a termination signal.

### Report Trigger & TUI Integration
- **D-04:** CLI-only trigger. `alphaswarm report --cycle <cycle_id>` as a new argparse subcommand following the existing `inject`/`run`/`tui` pattern in `cli.py`. No auto-trigger from TUI simulation flow.
- **D-05:** Sentinel file written on completion: `.alphaswarm/last_report.json` (project-root relative). Contains `{"cycle_id": "...", "path": "./reports/{cycle_id}_report.md", "generated_at": "ISO timestamp"}`. Created by aiofiles in the CLI handler.
- **D-06:** TUI's existing 200ms tick (`set_interval`) checks for the sentinel file. When found and newer than last tick, the `TelemetryFooter` (or `HeaderBar`) displays the report path inline — no new widget required. Sentinel file is polled, not watched with inotify/FSEvents.

### Report Sections (8 total)
- **D-07:** Report contains 8 distinct sections in this order:
  1. **Consensus Summary** — global BUY/SELL/HOLD breakdown (count + %) across all 100 agents for the final round
  2. **Round-by-Round Timeline** — global signal % per round (Rounds 1→2→3), showing sentiment evolution
  3. **Bracket Narratives** — per-bracket stance summary: dominant signal, avg confidence, avg sentiment per bracket
  4. **Key Dissenters** — agents whose signal diverges from their bracket majority in Round 3
  5. **Influence Leaders** — top agents by cumulative INFLUENCED_BY edge weight (most cited peers)
  6. **Signal Flip Analysis** — agents who changed position between rounds (uses flip_type from RationaleEpisode, Phase 11)
  7. **Entity Impact Analysis** — per-entity sentiment aggregation via REFERENCES edges (Phase 11 GRAPH-03)
  8. **Social Post Reach** — top rationale posts by READ_POST edge count (Phase 12 SOCIAL-01)
- **D-08:** One Cypher query tool per section = 8 tools total. Each tool is a named async method on `GraphStateManager` (or a dedicated `ReportQueryEngine` class — Claude's discretion). Tool input: `cycle_id` (always required), optional filters per tool.
- **D-09:** Jinja2 templates. Each section has a `.j2` template file in `src/alphaswarm/templates/report/`. Report assembler renders sections independently, concatenates, and writes to file. Requires adding `jinja2` to `pyproject.toml`.

### File Export
- **D-10:** Default output directory: `./reports/` (project-root relative). Created by the CLI handler if it doesn't exist. Default filename: `{cycle_id}_report.md`. Optional `--output` flag overrides the full path.
- **D-11:** Async file write via `aiofiles`. Requires adding `aiofiles` to `pyproject.toml`. Both `jinja2` and `aiofiles` are new dependencies.

### Orchestrator Model Lifecycle
- **D-12:** Report generation uses the orchestrator model (from STATE.md research: 30s swap). Model lifecycle must be serialized — report CLI cannot run while a TUI simulation or interview session is active. Enforcement is informational (CLI warning) for Phase 15, not a hard lock.

### Claude's Discretion
- Whether Cypher query tools live as methods on `GraphStateManager` or in a dedicated `ReportQueryEngine` class
- ReACT engine module name and file location (e.g., `report.py` or `react_agent.py`)
- Jinja2 template file structure (one master template vs per-section partials)
- Observation accumulation format (list of dicts, or structured `ToolObservation` dataclass)
- How the TUI polls the sentinel file (in `on_timer` callback vs existing `set_interval` tick method)
- Whether `--cycle` flag is required or defaults to most recent completed cycle (from Neo4j)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — REPORT-01 (ReACT agent, prompt-based tool dispatching, 8-10 iteration cap), REPORT-02 (Cypher tools: bracket summaries, influence topology, entity trends, signal flip metrics), REPORT-03 (markdown output, CLI report subcommand, aiofiles export)
- `.planning/ROADMAP.md` — Phase 15 success criteria (5 criteria including Jinja2 templates, orchestrator model lifecycle, structured sections)

### CLI (Primary)
- `src/alphaswarm/cli.py` — `main()` (line 633, argparse subcommand pattern for new `report` subparser), `_handle_run()` / `_handle_tui()` (patterns for async CLI handlers), `_print_round_report()` (existing inline report formatting to differentiate from)

### TUI (Primary — sentinel file integration)
- `src/alphaswarm/tui.py` — `TelemetryFooter` (existing footer widget where report path can be shown), `HeaderBar` (alternative display location), `AlphaSwarmApp` `set_interval` tick handler (where sentinel file polling goes)
- `src/alphaswarm/state.py` — `StateStore` and `AppState` (patterns for shared state, relevant if sentinel polling hooks into existing state layer)

### Graph Layer (Primary — Cypher query tools)
- `src/alphaswarm/graph.py` — `read_peer_decisions()` (line 606, async Cypher read pattern), `read_agent_interview_context()` (line 988, complex multi-node read pattern with OPTIONAL MATCH), `compute_influence_edges()` (line ~410, INFLUENCED_BY edge schema), `write_rationale_episodes()` (Phase 11, RationaleEpisode schema with flip_type), `GraphStateManager` (class structure for adding new read methods)
- `src/alphaswarm/graph.py` — `SCHEMA_STATEMENTS` (existing indexes; Phase 15 adds no new schema)

### Worker/Orchestrator Models
- `src/alphaswarm/worker.py` — `agent_worker()` context manager — NOT used by report agent (same as Phase 14 D-13 pattern)
- `src/alphaswarm/ollama_client.py` — `OllamaClient.chat()` — direct usage for orchestrator ReACT loop (bypass governor)
- `src/alphaswarm/seed.py` — orchestrator model loading pattern (inject_seed uses orchestrator; report agent follows same lifecycle)

### Prior Phase Context
- `.planning/phases/14-agent-interviews/14-CONTEXT.md` — D-12/D-13 (model lifecycle, direct OllamaClient.chat() for non-governor sessions), interview.py as structural template for report engine
- `.planning/phases/11-live-graph-memory/11-CONTEXT.md` — D-05/D-06 (flip_type enum, RationaleEpisode schema), D-10 (decision_narrative on Agent nodes)
- `.planning/phases/12-richer-agent-interactions/12-CONTEXT.md` — Post node schema, READ_POST edges, composite index pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `cli.py:main()` — argparse `add_parser("report")` goes in same `subparsers` block as `inject`/`run`/`tui`. Follows identical `--cycle` argument pattern.
- `interview.py` — `InterviewEngine` class structure (standalone module with `OllamaClient` injection, `async` run method) is the direct structural template for the ReACT report engine.
- `graph.py:read_agent_interview_context()` — OPTIONAL MATCH + multi-record result pattern for new Cypher query tools.
- `graph.py:compute_influence_edges()` — INFLUENCED_BY edge traversal pattern for the Influence Leaders query tool.
- `seed.py` — orchestrator model lifecycle (load → use → unload pattern) for report model management.

### Established Patterns
- Session-per-method on `GraphStateManager` for all Cypher reads
- `structlog` component-scoped logger: `logger = structlog.get_logger(component="report")`
- Pydantic dataclasses for typed tool outputs (frozen, validated)
- `asyncio.run()` in CLI sync handler wrapping async report coroutine

### Integration Points
- `cli.py:main()` — new `report` subparser + `_handle_report(cycle_id, output)` async handler
- `graph.py:GraphStateManager` — 8 new async read methods (one per report section/tool)
- `tui.py:AlphaSwarmApp` — sentinel file polling in `on_timer` or existing tick; `TelemetryFooter` or `HeaderBar` shows path
- New files: `src/alphaswarm/report.py` (ReACT engine + report assembler), `src/alphaswarm/templates/report/*.j2` (Jinja2 section templates)
- `pyproject.toml` — add `jinja2` and `aiofiles` to `[project.dependencies]`

</code_context>

<specifics>
## Specific Ideas

- The ReACT engine should read like a conversation with itself: `THOUGHT: I need bracket consensus first. ACTION: bracket_summary INPUT: {"cycle_id": "abc"}` — clean, human-readable logs via structlog.
- The 8 sections give enough depth to be genuinely useful as a post-simulation analysis tool. Order matters: start with global consensus, zoom into bracket detail, then surface outliers (dissenters, flippers), then influence dynamics, then entity and social dimensions.
- Sentinel file path `.alphaswarm/last_report.json` keeps it project-local and git-ignorable (add to .gitignore alongside `reports/`).
- Jinja2 section templates give flexibility for future report customization without touching Python — a nice clean boundary.

</specifics>

<deferred>
## Deferred Ideas

- Interactive report viewer in TUI (scrollable markdown panel) — future v3
- Auto-trigger report on `SimulationPhase.COMPLETE` from TUI — deferred, CLI-only for now
- Report export to HTML or PDF — deferred
- Parameterized report depth (e.g., `--sections consensus,brackets`) — future enhancement
- Hard lock preventing report CLI while TUI simulation is running — informational warning only in Phase 15

</deferred>

---

*Phase: 15-post-simulation-report*
*Context gathered: 2026-04-02*
