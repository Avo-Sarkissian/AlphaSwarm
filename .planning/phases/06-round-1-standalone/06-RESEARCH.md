# Phase 6: Round 1 Standalone - Research

**Researched:** 2026-03-26
**Domain:** Async pipeline orchestration, batch LLM inference, CLI composition, result aggregation
**Confidence:** HIGH

## Summary

Phase 6 is an integration phase -- it wires together existing, fully tested infrastructure into a single end-to-end pipeline. All core building blocks already exist: `inject_seed()` for orchestrator parsing, `dispatch_wave()` for batched agent inference, `write_decisions()` for Neo4j persistence, `persona_to_worker_config()` for persona conversion, and `_handle_inject()` as the CLI handler template. No new infrastructure, libraries, or external dependencies are needed.

The primary engineering challenge is composing these pieces correctly with proper model lifecycle management (load orchestrator, unload, load worker, dispatch, unload worker) and building the bracket-level reporting logic. The `run` CLI command must coordinate seed injection, model swapping, wave dispatch of 100 agents, Neo4j batch write, and formatted terminal output in a single async pipeline. Error handling for partial failures (PARSE_ERROR agents) must be reflected accurately in both the Neo4j persistence and the terminal report.

**Primary recommendation:** Build this as a thin orchestration layer (`simulation.py` or `round1.py`) that composes existing functions, plus a `_handle_run()` CLI handler and `_print_round1_report()` formatting function. The new code should be under 200 lines total. Keep the pipeline linear and simple -- no state machine, no parallelism beyond what `dispatch_wave()` already provides.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Unified `run` CLI subcommand -- `python -m alphaswarm run "rumor text"` executes the full pipeline: inject seed, unload orchestrator, load worker, dispatch wave, persist decisions, report results. One command, end-to-end.
- **D-02:** The `run` command reuses the existing `inject_seed()` pipeline internally. No separate `round1` subcommand -- keep CLI surface minimal for now.
- **D-03:** Sequential model lifecycle within the pipeline: orchestrator loads for seed parsing, unloads, then worker loads for agent inference. Follows INFRA-03 sequential loading contract.
- **D-04:** Raw rumor only as the user message for Round 1. Agents receive the natural-language rumor text, NOT the structured SeedEvent entities/sentiment. Each persona's system prompt already encodes archetype-specific biases and heuristics -- raw rumor forces diverse interpretation.
- **D-05:** Message format: system prompt (persona-specific) + user message (raw rumor). No peer_context in Round 1 (peer_context=None passed to dispatch_wave).
- **D-06:** Bracket summary table + top movers output. Bracket table shows signal counts (BUY/SELL/HOLD) and average confidence per bracket. Below that, "Notable Decisions" section highlights top 5 highest-confidence agents with signal, confidence, and rationale snippet.
- **D-07:** Report includes header with total agent count and success/failure breakdown (e.g., "100/100 agents" or "98/100 agents, 2 PARSE_ERROR").
- **D-08:** Neo4j-only state tracking for Round 1. Completion is implicit: 100 Decision nodes with (cycle_id, round=1) means done. No SharedStateStore phase transitions yet -- Phase 7 will introduce the state machine for the 3-round cascade.
- **D-09:** SimulationPhase enum already exists with ROUND_1/COMPLETE values -- available for Phase 7 when needed, not wired in Phase 6.

### Claude's Discretion
- Internal pipeline function structure (single `run_round1()` or composed from smaller functions)
- Worker model loading strategy within the pipeline (reuse model_manager patterns from seed.py)
- Bracket table formatting details (column widths, alignment)
- How to select "top 5 by confidence" -- simple sort on AgentDecision.confidence
- Error handling for partial wave failures (PARSE_ERROR agents still counted in bracket totals)
- Whether to print progress indicators during the wave dispatch

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIM-04 | Round 1 (Initial Reaction) -- all 100 agents process the seed rumor independently with no peer context | Pipeline composes inject_seed() + dispatch_wave(peer_context=None) + write_decisions(round_num=1). All building blocks exist. D-04/D-05 lock the message format. |
</phase_requirements>

## Standard Stack

### Core (Already Installed -- No New Dependencies)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| asyncio (stdlib) | 3.11+ | Pipeline orchestration, TaskGroup dispatch | Already in use |
| argparse (stdlib) | 3.11+ | CLI subparser for `run` command | Already in use |
| structlog | >=25.5.0 | Component-scoped logging | Already in use |
| ollama-python | >=0.6.1 | LLM inference client | Already in use |
| neo4j | >=5.28,<6.0 | Graph persistence | Already in use |
| pydantic | >=2.12.5 | Type validation (AgentDecision, SeedEvent) | Already in use |

### No New Dependencies Required
This phase introduces zero new libraries. It composes existing modules only.

## Architecture Patterns

### Recommended New File Structure
```
src/alphaswarm/
    simulation.py     # NEW: run_round1() pipeline orchestration
    cli.py            # MODIFIED: add `run` subparser + _handle_run() + _print_round1_report()
```

### Pattern 1: Pipeline Composition
**What:** The `run_round1()` function composes existing building blocks in a linear async pipeline.
**When to use:** Whenever a new feature is purely orchestrating existing subsystems.
**Recommended structure:**

```python
async def run_round1(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
) -> Round1Result:
    """End-to-end Round 1 pipeline: inject -> swap model -> dispatch -> persist -> report."""
    # 1. Inject seed (reuses existing pipeline -- loads/unloads orchestrator internally)
    cycle_id, parsed_result = await inject_seed(rumor, settings, ollama_client, model_manager, graph_manager)

    # 2. Load worker model (orchestrator already unloaded by inject_seed's finally block)
    worker_alias = settings.ollama.worker_model_alias
    await model_manager.load_model(worker_alias)
    try:
        # 3. Convert personas to worker configs
        worker_configs = [persona_to_worker_config(p) for p in personas]

        # 4. Dispatch wave (peer_context=None for Round 1)
        decisions = await dispatch_wave(
            personas=worker_configs,
            governor=governor,
            client=ollama_client,
            model=worker_alias,
            user_message=rumor,  # D-04: raw rumor, not structured entities
            settings=settings.governor,
            peer_context=None,  # D-05: no peer context in Round 1
        )

        # 5. Pair agent_ids with decisions for persistence
        agent_decisions = list(zip([wc["agent_id"] for wc in worker_configs], decisions))

        # 6. Batch write to Neo4j
        await graph_manager.write_decisions(agent_decisions, cycle_id, round_num=1)

    finally:
        # 7. Always unload worker model
        await model_manager.unload_model(worker_alias)

    return Round1Result(
        cycle_id=cycle_id,
        parsed_result=parsed_result,
        agent_decisions=agent_decisions,
        decisions=decisions,
    )
```

### Pattern 2: Result Container Dataclass
**What:** A frozen dataclass to bundle Round 1 results for both CLI reporting and future programmatic use.
**When to use:** When a pipeline produces multiple related outputs consumed by different downstream code.

```python
@dataclasses.dataclass(frozen=True)
class Round1Result:
    """Immutable result container for the Round 1 pipeline."""
    cycle_id: str
    parsed_result: ParsedSeedResult
    agent_decisions: list[tuple[str, AgentDecision]]
    decisions: list[AgentDecision]
```

### Pattern 3: CLI Handler (follows _handle_inject template)
**What:** The `_handle_run()` async function follows the identical lifecycle pattern from `_handle_inject()`.
**When to use:** Every CLI subcommand handler.

Key pattern elements:
1. `AppSettings()` + `load_bracket_configs()` + `generate_personas()`
2. `create_app_state(settings, personas, with_ollama=True, with_neo4j=True)`
3. Assert non-None on ollama_client, model_manager, graph_manager
4. `ensure_schema()` for idempotent Neo4j setup
5. Pipeline call
6. Print formatted results
7. `graph_manager.close()` in finally block

### Pattern 4: Bracket Aggregation for Reporting
**What:** Group decisions by bracket, compute signal counts and average confidence per bracket.
**When to use:** D-06 bracket summary table output.

```python
from collections import defaultdict

def _aggregate_brackets(
    agent_decisions: list[tuple[str, AgentDecision]],
    personas: list[AgentPersona],
) -> dict[str, dict]:
    """Aggregate decisions by bracket for reporting."""
    # Build agent_id -> bracket lookup
    bracket_lookup = {p.id: p.bracket.value for p in personas}
    # NOTE: Use display_name from BracketConfig for pretty output
    brackets: dict[str, list[AgentDecision]] = defaultdict(list)
    for agent_id, decision in agent_decisions:
        if decision.signal != SignalType.PARSE_ERROR:
            bracket = bracket_lookup.get(agent_id, "unknown")
            brackets[bracket].append(decision)
    # ... compute counts and avg confidence per bracket
```

### Anti-Patterns to Avoid
- **Creating a new CLI entry point for Round 1:** D-02 locks this as the `run` command reusing `inject_seed()`. No separate `round1` subcommand.
- **Passing structured SeedEvent to agents:** D-04 requires raw rumor text only. Agents receive the natural-language rumor, not extracted entities.
- **Adding state machine transitions:** D-08 explicitly defers state machine wiring to Phase 7. No SimulationPhase transitions in Phase 6.
- **Loading both models simultaneously:** INFRA-03 contract requires strict sequential loading. The orchestrator must fully unload before the worker loads.
- **Hand-rolling batch dispatch:** All agent calls MUST go through `dispatch_wave()` (INFRA-07). No bare `create_task` calls.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Seed injection pipeline | Custom orchestrator LLM calling | `inject_seed()` from `seed.py` | Already handles model lifecycle, parsing, persistence, error logging |
| Batch agent dispatch | Custom TaskGroup or create_task loop | `dispatch_wave()` from `batch_dispatcher.py` | Handles jitter, governor integration, failure tracking, PARSE_ERROR conversion |
| Decision persistence | Individual Neo4j transactions | `graph_manager.write_decisions()` | UNWIND batch write, CITED relationship handling, error wrapping |
| Persona conversion | Manual dict construction | `persona_to_worker_config()` from `config.py` | Handles lazy import, field mapping, type conversion |
| Concurrency control | Manual semaphore management | `ResourceGovernor` via `dispatch_wave()` | TokenPool, state machine, memory monitoring, crisis handling |
| Model lifecycle | Custom model loading/unloading | `OllamaModelManager.load_model()/unload_model()` | Lock serialization, ps() verification, keep_alive management |

**Key insight:** Phase 6 introduces no new infrastructure. Every building block exists and is tested. The only new code is (1) the pipeline composition function, (2) the CLI handler, and (3) the bracket summary formatter. Total new code should be under 200 lines.

## Common Pitfalls

### Pitfall 1: Model Lifecycle Race Between inject_seed and Worker Load
**What goes wrong:** `inject_seed()` has its own try/finally that unloads the orchestrator. If you also try to unload the orchestrator externally, you get a double-unload or the worker load races with the orchestrator unload.
**Why it happens:** `inject_seed()` is self-contained -- it manages the orchestrator lifecycle internally.
**How to avoid:** After `inject_seed()` returns, the orchestrator is already unloaded. Simply load the worker model directly. Do NOT unload the orchestrator again.
**Warning signs:** `ModelLoadError` on worker load, or ps() showing unexpected model state.

### Pitfall 2: Agent ID Ordering Mismatch Between Dispatch and Persistence
**What goes wrong:** `dispatch_wave()` returns a list of `AgentDecision` objects in the same order as the input `personas` list. If you zip these with agent IDs from a different ordering, decisions get attributed to wrong agents.
**Why it happens:** The zip between worker_configs and results depends on positional alignment.
**How to avoid:** Build `worker_configs` from the same `personas` list, then zip `worker_configs[i]["agent_id"]` with `decisions[i]`. Never reorder either list independently.
**Warning signs:** Agent brackets in Neo4j don't match expected distributions.

### Pitfall 3: PARSE_ERROR Decisions in Bracket Aggregation
**What goes wrong:** Including PARSE_ERROR decisions in bracket signal counts produces misleading statistics (e.g., "Quants: 7 SELL, 2 HOLD, 1 PARSE_ERROR" instead of excluding the error).
**Why it happens:** D-06 says bracket table shows BUY/SELL/HOLD counts. PARSE_ERROR is a 4th signal type that should not appear in bracket tables.
**How to avoid:** Filter out PARSE_ERROR decisions from bracket aggregation. Count them separately in the header (D-07: "98/100 agents, 2 failed").
**Warning signs:** Signal counts per bracket not summing to expected bracket count.

### Pitfall 4: Forgetting to Unload Worker Model on Pipeline Error
**What goes wrong:** If `dispatch_wave()` or `write_decisions()` raises an exception after the worker model is loaded, the worker model stays in VRAM consuming ~4GB.
**Why it happens:** No try/finally around the worker model lifecycle.
**How to avoid:** Wrap the worker model usage in try/finally, mirroring the pattern in `inject_seed()` for the orchestrator.
**Warning signs:** `ollama ps` shows the worker model still loaded after a failed run.

### Pitfall 5: Neo4j Schema Not Applied Before write_decisions
**What goes wrong:** If `ensure_schema()` is not called before `write_decisions()`, the Decision indexes may not exist, causing slow writes or constraint violations.
**Why it happens:** `_handle_inject()` calls `ensure_schema()` explicitly, but a new `_handle_run()` might forget.
**How to avoid:** Call `graph_manager.ensure_schema()` in `_handle_run()` before calling the pipeline, matching `_handle_inject()` pattern.
**Warning signs:** Neo4j write errors or slow batch performance.

### Pitfall 6: GovernorSettings Passed Incorrectly to dispatch_wave
**What goes wrong:** `dispatch_wave()` takes a `GovernorSettings` object for jitter and threshold config. Passing the wrong settings or a bare `GovernorSettings()` instead of `settings.governor` uses default jitter values instead of user-configured values.
**Why it happens:** The parameter name is `settings` which is ambiguous with `AppSettings`.
**How to avoid:** Always pass `settings.governor` (the `GovernorSettings` nested model from `AppSettings`).
**Warning signs:** Jitter timing or failure thresholds not matching `.env` configuration.

## Code Examples

### Example 1: Complete Pipeline Function Signature
```python
# Source: Pattern derived from inject_seed() in seed.py and dispatch_wave() in batch_dispatcher.py
async def run_round1(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
) -> Round1Result:
```

### Example 2: Bracket Summary Table Formatting (D-06)
```python
# Bracket table: bracket name, BUY count, SELL count, HOLD count, avg confidence
def _print_round1_report(result: Round1Result, personas: list[AgentPersona]) -> None:
    total = len(result.decisions)
    errors = sum(1 for d in result.decisions if d.signal == SignalType.PARSE_ERROR)
    success = total - errors

    # Header (D-07)
    print(f"\n{'='*60}")
    print("  Round 1 Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID: {result.cycle_id}")
    if errors > 0:
        print(f"  Agents:   {success}/{total} ({errors} PARSE_ERROR)")
    else:
        print(f"  Agents:   {total}/{total}")

    # Bracket table (D-06)
    # ... aggregate by bracket, print formatted table ...

    # Notable Decisions -- top 5 by confidence (D-06)
    valid = [(aid, d) for aid, d in result.agent_decisions if d.signal != SignalType.PARSE_ERROR]
    top5 = sorted(valid, key=lambda x: x[1].confidence, reverse=True)[:5]
    # ... print formatted top movers ...
```

### Example 3: CLI run Subparser Addition
```python
# Source: Pattern from cli.py inject subparser
run_parser = subparsers.add_parser("run", help="Run full Round 1 simulation")
run_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")
```

### Example 4: write_decisions Call with Round 1 Params
```python
# Source: graph.py write_decisions() signature
# agent_decisions is list[tuple[str, AgentDecision]]
await graph_manager.write_decisions(agent_decisions, cycle_id, round_num=1)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate inject + round1 CLI commands | Unified `run` command (D-01) | Phase 6 CONTEXT | Single command for full simulation pass |
| Structured entities as agent input | Raw rumor text for agents (D-04) | Phase 6 CONTEXT | More diverse agent interpretations |
| State machine phase tracking | Implicit Neo4j completion tracking (D-08) | Phase 6 CONTEXT | Simpler Phase 6, state machine deferred to Phase 7 |

## Open Questions

1. **Progress Indicators During Wave Dispatch**
   - What we know: 100 agents dispatching in batches of 8-16 will take several minutes. Silent execution may concern the user.
   - What's unclear: CONTEXT.md puts this in Claude's discretion.
   - Recommendation: Print a simple progress counter (e.g., "Dispatching agents... 50/100") to stdout. Use structlog for detailed per-agent logging at DEBUG level. This adds minimal code and prevents user confusion during long runs.

2. **Rationale Snippet Length in Top 5 Notable Decisions**
   - What we know: D-06 says "rationale snippet" for top 5 agents.
   - What's unclear: How long the snippet should be.
   - Recommendation: Truncate rationale to 80 characters with "..." suffix. This fits in a terminal line and provides enough context.

3. **Bracket Display Name Mapping**
   - What we know: Agent IDs use `BracketType.value` (e.g., "doom_posters"). Display names are on `BracketConfig.display_name` (e.g., "Doom-Posters").
   - What's unclear: Whether to use display names in the report table.
   - Recommendation: Use `BracketConfig.display_name` in the report for readability. Build a value-to-display-name lookup from bracket configs.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-04-a | Pipeline calls inject_seed then dispatch_wave with peer_context=None | unit | `uv run pytest tests/test_simulation.py::test_run_round1_dispatches_with_no_peer_context -x` | Wave 0 |
| SIM-04-b | Pipeline loads worker model after orchestrator unloads | unit | `uv run pytest tests/test_simulation.py::test_run_round1_loads_worker_after_orchestrator -x` | Wave 0 |
| SIM-04-c | Pipeline unloads worker model in finally block | unit | `uv run pytest tests/test_simulation.py::test_run_round1_unloads_worker_on_error -x` | Wave 0 |
| SIM-04-d | Pipeline calls write_decisions with round_num=1 | unit | `uv run pytest tests/test_simulation.py::test_run_round1_persists_decisions_round_1 -x` | Wave 0 |
| SIM-04-e | Pipeline passes raw rumor (not entities) to dispatch_wave | unit | `uv run pytest tests/test_simulation.py::test_run_round1_passes_raw_rumor_to_agents -x` | Wave 0 |
| SIM-04-f | CLI `run` subparser parses rumor argument | unit | `uv run pytest tests/test_cli.py::test_parse_run_args -x` | Wave 0 |
| SIM-04-g | CLI `_handle_run` calls asyncio.run with pipeline | unit | `uv run pytest tests/test_cli.py::test_main_run_calls_asyncio_run -x` | Wave 0 |
| SIM-04-h | Report shows bracket signal distribution | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_bracket_table -x` | Wave 0 |
| SIM-04-i | Report shows top 5 notable decisions | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_notable_decisions -x` | Wave 0 |
| SIM-04-j | Report header shows success/failure count | unit | `uv run pytest tests/test_cli.py::test_print_round1_report_header_with_failures -x` | Wave 0 |
| SIM-04-k | PARSE_ERROR agents excluded from bracket counts | unit | `uv run pytest tests/test_cli.py::test_bracket_aggregation_excludes_parse_errors -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_simulation.py` -- covers SIM-04-a through SIM-04-e (pipeline unit tests with mocked dependencies)
- [ ] New tests in `tests/test_cli.py` -- covers SIM-04-f through SIM-04-k (CLI handler and report formatting)
- No new framework install needed -- pytest-asyncio already configured with `asyncio_mode = "auto"`
- No new conftest fixtures needed beyond what's in place (mock_governor, sample_personas patterns are reusable)

## Project Constraints (from CLAUDE.md)

| Directive | Enforcement |
|-----------|-------------|
| 100% async (asyncio), no blocking I/O on main event loop | Pipeline function must be async. CLI handler uses `asyncio.run()` wrapper |
| Local first, all inference via Ollama | dispatch_wave routes through OllamaClient. No cloud APIs |
| Max 2 models loaded simultaneously | Sequential model loading: orchestrator unloads before worker loads (D-03) |
| Monitor RAM via psutil, throttle at 80%, pause at 90% | ResourceGovernor handles this via dispatch_wave integration |
| Python 3.11+, strict typing | All new functions must have full type annotations |
| uv as package manager | `uv run pytest` for testing |
| pytest-asyncio for tests | asyncio_mode="auto" already configured |
| structlog for logging | Use structlog.get_logger(component="simulation") for new module |

## Sources

### Primary (HIGH confidence)
- **Existing codebase** -- All source files in `src/alphaswarm/` read and analyzed. Every building block verified as implemented and tested.
- **Existing test suite** -- 238 tests passing, confirming all infrastructure is functional.
- **06-CONTEXT.md** -- All 9 locked decisions and discretion areas documented.

### Secondary (MEDIUM confidence)
- **Prior phase CONTEXT files** -- Referenced for architectural consistency (Phase 3 D-04 through D-06, Phase 5 decisions).

### Tertiary (LOW confidence)
- None. This phase requires no external library research -- it is purely an integration of existing code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all libraries already installed and tested
- Architecture: HIGH -- pipeline pattern directly mirrors existing inject_seed() pattern; all integration points verified in source code
- Pitfalls: HIGH -- derived from reading actual code paths and identifying real error modes

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- no external dependencies to drift)
