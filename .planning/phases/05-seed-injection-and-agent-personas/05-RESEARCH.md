# Phase 5: Seed Injection and Agent Personas - Research

**Researched:** 2026-03-25
**Domain:** LLM-driven entity extraction, agent persona system, CLI pipeline, Neo4j entity persistence
**Confidence:** HIGH

## Summary

Phase 5 bridges infrastructure (Phases 1-4) and simulation logic (Phases 6-8) by delivering two core capabilities: (1) an orchestrator LLM pipeline that parses natural-language seed rumors into structured `SeedEvent` objects with named entities and sentiment scores, and (2) enriched agent personas with archetype-specific decision heuristics, information biases, and per-agent personality variation. A CLI `inject` subcommand ties the pipeline together end-to-end.

The codebase is well-prepared. `OllamaClient.chat()` already supports `format="json"` and `think` parameters. `parse_agent_decision()` in `parsing.py` provides the exact 3-tier fallback pattern to replicate for `parse_seed_event()`. `GraphStateManager` has the session-per-method and UNWIND+MERGE patterns ready to extend with entity node persistence. `generate_personas()` in `config.py` has TODO markers on all 10 bracket system prompts awaiting refinement. The main risk is the **think+format incompatibility** in Ollama -- using `think=True` with `format="json"` silently disables thinking mode. The implementation must handle this correctly.

**Primary recommendation:** Use `format="json"` (or Pydantic schema-constrained format) for reliable structured output from the orchestrator, and compensate for the thinking mode limitation through detailed prompt engineering rather than relying on `think=True`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** SeedEvent is a frozen Pydantic model: `raw_rumor: str`, `entities: list[SeedEntity]`, `overall_sentiment: float`
- **D-02:** SeedEntity includes: `name: str`, `type: EntityType` (company/sector/person enum), `relevance: float` (0.0-1.0), `sentiment: float` (-1.0 to 1.0)
- **D-03:** Entity nodes persisted as `(:Entity)` in Neo4j linked to Cycle via `(:Cycle)-[:MENTIONS]->(:Entity)`
- **D-04:** Use `OllamaClient.chat()` with `format="json"` for seed parsing
- **D-05:** Thinking mode enabled (`think=True`) for orchestrator during entity extraction
- **D-06:** Dedicated `parse_seed_event()` function in `parsing.py` with 3-tier fallback pattern
- **D-07:** Orchestrator model lifecycle managed within seed injection pipeline (load, run, unload)
- **D-08:** Medium prompt depth -- expand system_prompt_template to ~150-250 words per bracket
- **D-09:** Per-agent variation via 3-5 personality modifiers per bracket, round-robin assigned
- **D-10:** System prompts include explicit JSON output formatting instructions at the end
- **D-11:** New `src/alphaswarm/cli.py` module with subcommand routing; `__main__.py` becomes thin shim
- **D-12:** Seed rumor via CLI argument: `python -m alphaswarm inject "NVIDIA announces..."`
- **D-13:** CLI outputs structured summary: cycle_id, entities with relevance/sentiment, overall sentiment

### Claude's Discretion
- SeedEvent Pydantic model field ordering and validation constraints
- EntityType enum values and naming
- Orchestrator system prompt wording for entity extraction
- Specific personality modifier pool for each bracket
- CLI argument parser library choice (argparse vs click vs typer)
- Neo4j Entity node index definitions
- Graph relationship naming (MENTIONS vs EXTRACTS vs CONTAINS)
- Output formatting details (table library, color, layout)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIM-01 | Orchestrator LLM parses seed rumor and extracts named entities as structured JSON | OllamaClient.chat() with format param + parse_seed_event() 3-tier fallback + SeedEvent/SeedEntity Pydantic models |
| SIM-02 | 100 agents across 10 bracket archetypes with distinct risk profiles, information biases, and decision heuristics | Expand DEFAULT_BRACKETS system_prompt_template to ~150-250 words + per-agent personality modifiers via round-robin |
| SIM-03 | Each agent produces structured decision: signal, confidence, sentiment, rationale, cited_agents | AgentDecision model already exists with all fields; worker.infer() already produces parsed decisions; system prompts need JSON schema instructions appended |
</phase_requirements>

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ollama | 0.6.1 | LLM inference client with `chat()`, `format`, `think` params | Already integrated; supports JSON mode and schema-constrained output |
| pydantic | 2.12.5 | Frozen domain models (SeedEvent, SeedEntity, EntityType) | Project convention for all domain types |
| neo4j | 5.28.3 | Async graph driver for Entity node persistence | Already integrated with session-per-method pattern |
| structlog | (installed) | Component-scoped logging | Project convention: `structlog.get_logger(component="...")` |

### Supporting (Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| backoff | 2.2.1 | Exponential retry on OllamaClient | Already wired into `_chat_with_backoff` |
| pydantic-settings | (installed) | AppSettings env loading | Already used for configuration |

### No New Dependencies Required
This phase requires **zero new packages**. All functionality builds on existing infrastructure:
- `argparse` (stdlib) for CLI subcommand routing -- no need for click/typer given the simple `inject` subcommand
- No table formatting library needed -- use simple f-string formatted output for the CLI summary

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse (stdlib) | click/typer | click/typer add dependencies for a single subcommand; argparse is sufficient and zero-dependency |
| f-string formatting | rich/tabulate | Over-engineered for 5-10 entity rows; future phases can add rich if TUI needs it |
| format="json" | SeedEvent.model_json_schema() | Schema-constrained format is more reliable but may not work with think=True; see Pitfall 1 |

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
|-- cli.py              # NEW: Subcommand router (inject subcommand)
|-- seed.py             # NEW: Seed injection pipeline (parse_seed_event orchestration)
|-- types.py            # EXTEND: Add SeedEvent, SeedEntity, EntityType
|-- config.py           # EXTEND: Expand system_prompt_templates, add personality modifiers
|-- parsing.py          # EXTEND: Add parse_seed_event() alongside parse_agent_decision()
|-- graph.py            # EXTEND: Add write_seed_event(), Entity schema statements
|-- __main__.py         # MODIFY: Thin shim delegating to cli.py
```

### Pattern 1: Seed Injection Pipeline (seed.py)
**What:** Self-contained async pipeline: load orchestrator model -> chat with format="json" -> parse response -> persist to Neo4j -> unload model
**When to use:** Called by CLI `inject` subcommand
**Example:**
```python
# Source: Existing OllamaModelManager pattern + CONTEXT.md D-07
async def inject_seed(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
) -> SeedEvent:
    """End-to-end seed injection pipeline."""
    # 1. Load orchestrator model
    await model_manager.load_model(settings.ollama.orchestrator_model_alias)
    try:
        # 2. Chat with format="json" for structured extraction
        response = await ollama_client.chat(
            model=settings.ollama.orchestrator_model_alias,
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": rumor},
            ],
            format="json",  # or SeedEvent.model_json_schema()
            think=True,     # SEE PITFALL 1: may be silently ignored
        )
        # 3. Parse with 3-tier fallback
        seed_event = parse_seed_event(response.message.content or "", rumor)
        # 4. Persist to Neo4j
        cycle_id = await graph_manager.create_cycle(rumor)
        await graph_manager.write_seed_event(cycle_id, seed_event)
        return seed_event
    finally:
        # 5. Unload orchestrator model
        await model_manager.unload_model(settings.ollama.orchestrator_model_alias)
```

### Pattern 2: 3-Tier Parse Fallback for SeedEvent
**What:** Replicate the `parse_agent_decision()` pattern for `parse_seed_event()`
**When to use:** Parsing orchestrator LLM output into SeedEvent
**Example:**
```python
# Source: Existing parsing.py pattern (lines 42-118)
def parse_seed_event(raw: str, original_rumor: str) -> SeedEvent:
    """Parse orchestrator output into SeedEvent with 3-tier fallback."""
    # Tier 1: Direct JSON validation
    try:
        return SeedEvent.model_validate_json(raw)
    except (ValidationError, ValueError):
        pass
    # Tier 2: Code fence strip + regex extraction
    cleaned = _strip_code_fences(raw)
    # ... same pattern as parse_agent_decision ...
    # Tier 3: Minimal fallback -- return SeedEvent with empty entities
    return SeedEvent(
        raw_rumor=original_rumor,
        entities=[],
        overall_sentiment=0.0,
    )
```

### Pattern 3: Per-Agent Personality Modifier Round-Robin
**What:** Deterministic assignment of personality modifiers within each bracket
**When to use:** Extending `generate_personas()` for per-agent variation (D-09)
**Example:**
```python
# Source: CONTEXT.md D-09
BRACKET_MODIFIERS: dict[BracketType, list[str]] = {
    BracketType.QUANTS: [
        "conservative quantitative analyst",
        "aggressive statistical arbitrageur",
        "risk-averse factor modeler",
        "momentum-focused data scientist",
    ],
    # ... 9 more brackets
}

def generate_personas(brackets: list[BracketConfig]) -> list[AgentPersona]:
    for bracket in brackets:
        modifiers = BRACKET_MODIFIERS.get(bracket.bracket_type, [])
        for i in range(1, bracket.count + 1):
            modifier = modifiers[(i - 1) % len(modifiers)] if modifiers else ""
            system_prompt = _build_system_prompt(bracket, agent_name, modifier)
            # ... rest of persona creation
```

### Pattern 4: CLI Subcommand with asyncio.run()
**What:** argparse subcommand routing with async handler invocation
**When to use:** `python -m alphaswarm inject "rumor text"`
**Example:**
```python
# Source: stdlib argparse + CONTEXT.md D-11, D-12
import argparse
import asyncio

def main() -> None:
    parser = argparse.ArgumentParser(prog="alphaswarm")
    subparsers = parser.add_subparsers(dest="command")
    inject_parser = subparsers.add_parser("inject", help="Inject a seed rumor")
    inject_parser.add_argument("rumor", type=str, help="Natural-language seed rumor")
    args = parser.parse_args()
    if args.command == "inject":
        asyncio.run(_handle_inject(args.rumor))
    else:
        # Legacy banner behavior
        _print_banner()
```

### Anti-Patterns to Avoid
- **Calling OllamaClient.chat() without the pipeline context:** All orchestrator calls must go through the seed injection pipeline to ensure model lifecycle (load/unload) is managed
- **Using think=True with format constraints and expecting reasoning output:** The format parameter suppresses thinking tokens; do not assert on `response.message.thinking` content
- **Modifying BracketConfig at runtime:** BracketConfig is frozen; personality modifiers are applied during persona generation, not by mutating bracket configs
- **Creating Entity nodes one at a time:** Use UNWIND+MERGE batch pattern consistent with existing graph writes

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing with fallback | Custom JSON parser | Pydantic `model_validate_json()` + existing 3-tier pattern | Edge cases around code fences, nested JSON, validation are already solved |
| Model lifecycle management | Manual load/unload tracking | `OllamaModelManager.load_model()`/`unload_model()` | Lock-serialized, ps()-verified, exception-safe |
| CLI argument parsing | Manual sys.argv parsing | `argparse` stdlib | Battle-tested, generates help text, handles edge cases |
| Neo4j batch writes | Loop of individual CREATEs | UNWIND+MERGE pattern from existing `graph.py` | 100x fewer round trips, idempotent |
| Structured output enforcement | Regex-based JSON extraction alone | Ollama `format="json"` or `format=Model.model_json_schema()` | Grammar-constrained decoding at token level is more reliable |

**Key insight:** Every infrastructure piece needed for Phase 5 already exists in the codebase. The work is composing existing patterns (OllamaClient, ModelManager, GraphStateManager, parsing fallback) into a new pipeline, plus enriching the persona system prompts.

## Common Pitfalls

### Pitfall 1: think=True Silently Disabled by format="json"
**What goes wrong:** Decision D-05 specifies `think=True` for the orchestrator, but Ollama's `format` parameter suppresses the `<think>` token, effectively disabling thinking mode. The call succeeds but no reasoning occurs.
**Why it happens:** Ollama's structured output grammar constrains the token probabilities at decode time. The `<think>` token gets zero probability because it's not valid JSON.
**How to avoid:** Two options:
1. **Accept the limitation:** Use `format="json"` without `think=True`. Compensate with a detailed system prompt that instructs the model to reason step-by-step within the JSON output (e.g., include a "reasoning" field).
2. **Two-step approach (expensive):** First call with `think=True` and no format constraint to get reasoning, then second call with `format="json"` to get structured output. Doubles inference time.
**Recommendation:** Option 1. The orchestrator is called once per seed injection; the quality difference from thinking mode is marginal compared to good prompt engineering. Include a `reasoning` or `analysis` field in the prompt instructions if chain-of-thought is desired.
**Warning signs:** `response.message.thinking` is `None` or empty when `think=True` and `format` is set.
**Confidence:** HIGH -- verified via GitHub issues [#10538](https://github.com/ollama/ollama/issues/10538), [#235](https://github.com/ollama/ollama-js/issues/235), [#10929](https://github.com/ollama/ollama/issues/10929)

### Pitfall 2: SeedEvent Parse Failure on Empty Entity List
**What goes wrong:** The orchestrator might return `{"entities": [], "overall_sentiment": 0.0}` for vague rumors with no clear entities. If `raw_rumor` is not included in the LLM output, Tier 1 parse fails on missing required field.
**Why it happens:** The LLM only outputs what it generates; `raw_rumor` is a metadata field that must be injected by the caller.
**How to avoid:** `parse_seed_event()` should accept the original rumor text as a parameter and inject it into the parsed result, not expect it in the LLM output. The prompt should only request entities and sentiment.
**Warning signs:** Validation errors on `raw_rumor` field during parsing.

### Pitfall 3: Persona System Prompt Exceeding Worker Context Window
**What goes wrong:** D-08 specifies ~150-250 word system prompts. With JSON output instructions (D-10) appended, total system prompt might reach 300+ words (~400 tokens). The worker model (`qwen3.5:7b`) has limited context.
**Why it happens:** System prompt + user message (seed rumor can be 50-200 words) + peer context (Rounds 2-3) must all fit in the context window.
**How to avoid:** Keep system prompts under 250 words including JSON instructions. The JSON output schema instructions should be concise (~50 words). Test with longest realistic prompts.
**Warning signs:** Truncated or garbled agent responses; rationale field empty.

### Pitfall 4: Entity Node Uniqueness Across Cycles
**What goes wrong:** If two cycles mention "NVIDIA", MERGE on name alone creates one shared node. This may or may not be desired.
**Why it happens:** MERGE matches on the specified properties.
**How to avoid:** Per D-03, entities are linked to cycles via `(:Cycle)-[:MENTIONS]->(:Entity)`. Use `MERGE (e:Entity {name: $name, type: $type})` for cross-cycle entity identity (intended -- "which rumors mentioned NVIDIA"). The MENTIONS relationship carries cycle-specific relevance and sentiment.
**Warning signs:** Unexpected entity counts after multiple cycles.

### Pitfall 5: CLI asyncio.run() Conflicts with Existing Event Loop
**What goes wrong:** If `__main__.py` is run inside an environment that already has a running event loop (e.g., Jupyter, some test runners), `asyncio.run()` raises `RuntimeError`.
**Why it happens:** `asyncio.run()` creates a new event loop and cannot nest.
**How to avoid:** Use `asyncio.run()` only at the top-level CLI entry point. Tests should use `pytest-asyncio` markers, not `asyncio.run()`.
**Warning signs:** `RuntimeError: This event loop is already running`.

### Pitfall 6: Round-Robin Modifier Assignment Sensitivity to Bracket Count Changes
**What goes wrong:** If bracket counts change (e.g., Degens from 20 to 15), the round-robin assignment of personality modifiers shifts, changing which agent gets which modifier. This breaks reproducibility of past runs.
**Why it happens:** Modulo-based assignment depends on count.
**How to avoid:** This is acceptable for v1 -- modifier assignment is deterministic for a given config. Document that changing bracket counts changes persona assignments.
**Warning signs:** Different simulation results after config changes with same seed rumor.

## Code Examples

### SeedEvent and SeedEntity Pydantic Models
```python
# Source: CONTEXT.md D-01, D-02 + existing types.py pattern
from enum import Enum
from pydantic import BaseModel, Field

class EntityType(str, Enum):
    """Named entity types extracted from seed rumors."""
    COMPANY = "company"
    SECTOR = "sector"
    PERSON = "person"

class SeedEntity(BaseModel, frozen=True):
    """A single named entity extracted from a seed rumor."""
    name: str
    type: EntityType
    relevance: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0)

class SeedEvent(BaseModel, frozen=True):
    """Structured seed rumor with extracted entities."""
    raw_rumor: str
    entities: list[SeedEntity]
    overall_sentiment: float = Field(ge=-1.0, le=1.0)
```

### Neo4j Entity Write Pattern
```python
# Source: Existing graph.py UNWIND+MERGE pattern
@staticmethod
async def _write_seed_event_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    entities: list[dict],
) -> None:
    """UNWIND+MERGE Entity nodes, then CREATE MENTIONS relationships."""
    await tx.run(
        """
        UNWIND $entities AS e
        MERGE (entity:Entity {name: e.name, type: e.type})
        WITH entity, e
        MATCH (c:Cycle {cycle_id: $cycle_id})
        CREATE (c)-[:MENTIONS {relevance: e.relevance, sentiment: e.sentiment}]->(entity)
        """,
        entities=entities,
        cycle_id=cycle_id,
    )
```

### Orchestrator System Prompt for Entity Extraction
```python
# Source: Claude's discretion area
ORCHESTRATOR_SYSTEM_PROMPT = """You are a financial intelligence analyst. Given a market rumor, extract:
1. Named entities (companies, sectors, people) with relevance scores and sentiment
2. Overall market sentiment

Respond with JSON containing:
- entities: list of {name, type (company/sector/person), relevance (0.0-1.0), sentiment (-1.0 to 1.0)}
- overall_sentiment: float (-1.0 to 1.0)

Be thorough: extract ALL entities mentioned or implied. Assign relevance based on how central each entity is to the rumor. Sentiment reflects the rumor's implication for that entity specifically."""
```

### Expanded System Prompt Template Example (Quants)
```python
# Source: CONTEXT.md D-08, D-09, D-10
QUANTS_TEMPLATE = """You are {modifier} in the Quantitative Analysis bracket.

PERSONALITY: You rely on statistical models, historical data patterns, and mathematical signals. Emotion is noise -- only the numbers matter. You discount narrative-driven arguments and weight quantitative evidence heavily.

DECISION HEURISTICS:
- Evaluate claims against historical precedent and base rates
- Assign higher confidence when multiple quantitative indicators align
- Default to HOLD when data is insufficient or contradictory

INFORMATION BIASES:
- Over-weight numerical data and under-weight qualitative narratives
- Skeptical of single-source information regardless of source authority
- Anchor strongly to recent price action and volatility metrics

Respond with a JSON object containing exactly these fields:
{{"signal": "buy"|"sell"|"hold", "confidence": 0.0-1.0, "sentiment": -1.0 to 1.0, "rationale": "your reasoning", "cited_agents": []}}"""
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| format="json" (unstructured) | format=Model.model_json_schema() (schema-constrained) | Ollama Dec 2024 | Grammar-level enforcement of output structure; more reliable than prompt-only JSON requests |
| No thinking support | think=True/False parameter | Ollama 2025 | Separate reasoning trace from final answer; BUT incompatible with format constraints |
| Manual JSON regex parsing | Pydantic model_validate_json() | Pydantic v2 | Type-safe validation with clear error messages |

**Deprecated/outdated:**
- Ollama `format="json"` + `think=True` combined: thinking is silently suppressed when format constraints are active. Do not rely on both simultaneously.

## Open Questions

1. **think=True + format="json" interaction at Ollama 0.18.1**
   - What we know: GitHub issues confirm incompatibility in Ollama core (not just clients). format suppresses thinking tokens.
   - What's unclear: Whether Ollama 0.18.1 (installed) has landed any fix from PR #10584. The project's installed version is newer than the issue reports.
   - Recommendation: Implement with `format="json"` and `think=True` set, but do NOT depend on thinking output. If `response.message.thinking` is populated, great. If not, the pipeline still works via structured output alone. Log a warning if thinking is empty when expected.

2. **Schema-constrained format vs simple "json" mode for orchestrator**
   - What we know: `format=SeedEvent.model_json_schema()` provides tighter constraints than `format="json"` but the schema excludes `raw_rumor` (which is caller-injected, not LLM-generated).
   - What's unclear: Whether schema-constrained mode works better with the specific Qwen3.5:32b model for entity extraction.
   - Recommendation: Start with `format="json"` (simpler, proven). The 3-tier fallback handles edge cases. If extraction quality is poor, upgrade to schema-constrained format in a follow-up.

3. **Personality modifier pool quality**
   - What we know: D-09 specifies 3-5 modifiers per bracket, round-robin assigned.
   - What's unclear: Whether the specific modifier wordings produce meaningfully different agent behaviors with qwen3.5:7b.
   - Recommendation: Design modifiers to cover a clear behavioral spectrum (risk-seeking to risk-averse, trend-following to contrarian). Validation is empirical -- Phase 6 Round 1 will reveal if diversity is sufficient.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | Yes | 3.11.5 (venv) | -- |
| uv | Package manager | Yes | 0.11.0 | -- |
| Ollama | LLM inference | Yes | 0.18.1 | -- |
| Docker | Neo4j container | Yes | 29.3.0 | -- |
| Neo4j (Docker) | Entity persistence | Yes (driver 5.28.3) | Container must be running | Skip Neo4j write in tests |
| ollama-python | Client library | Yes | 0.6.1 | -- |
| pydantic | Domain models | Yes | 2.12.5 | -- |

**Missing dependencies with no fallback:** None

**Missing dependencies with fallback:** None

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-01 | SeedEvent/SeedEntity Pydantic model validation | unit | `uv run pytest tests/test_seed.py -x -q` | No -- Wave 0 |
| SIM-01 | parse_seed_event() 3-tier fallback | unit | `uv run pytest tests/test_parsing.py -x -q` | Partial -- extend existing |
| SIM-01 | Orchestrator prompt returns valid entity JSON | integration | `uv run pytest tests/test_integration_inference.py -x -q` | Partial -- extend existing |
| SIM-01 | write_seed_event() persists Entity nodes to Neo4j | unit (mocked) | `uv run pytest tests/test_graph.py -x -q` | Partial -- extend existing |
| SIM-01 | write_seed_event() creates Entity+MENTIONS in live Neo4j | integration | `uv run pytest tests/test_graph_integration.py -x -q` | Partial -- extend existing |
| SIM-02 | Expanded system prompts ~150-250 words per bracket | unit | `uv run pytest tests/test_config.py -x -q` | Partial -- extend existing |
| SIM-02 | Per-agent personality modifiers round-robin assigned | unit | `uv run pytest tests/test_personas.py -x -q` | Partial -- extend existing |
| SIM-02 | 100 personas with distinct system prompts | unit | `uv run pytest tests/test_personas.py -x -q` | Partial -- extend existing |
| SIM-03 | System prompts include JSON output schema instructions | unit | `uv run pytest tests/test_config.py -x -q` | Partial -- extend existing |
| SIM-03 | AgentDecision model already validated | unit | `uv run pytest tests/test_parsing.py -x -q` | Yes -- existing |
| CLI | inject subcommand parses args and runs pipeline | unit | `uv run pytest tests/test_cli.py -x -q` | No -- Wave 0 |
| CLI | End-to-end inject writes SeedEvent to Neo4j | integration | `uv run pytest tests/test_graph_integration.py -x -q` | Partial -- extend existing |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py -q`
- **Per wave merge:** `uv run pytest tests/ -x -q` (includes integration if Docker + Ollama available)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_seed.py` -- SeedEvent, SeedEntity, EntityType model validation tests
- [ ] `tests/test_cli.py` -- CLI argument parsing and inject subcommand routing tests
- [ ] Extend `tests/test_parsing.py` -- parse_seed_event() 3-tier fallback tests
- [ ] Extend `tests/test_config.py` -- expanded system prompt length and modifier assignment tests
- [ ] Extend `tests/test_graph.py` -- write_seed_event() mock tests
- [ ] Extend `tests/conftest.py` -- SeedEvent fixtures, mock OllamaClient for orchestrator

## Project Constraints (from CLAUDE.md)

| Directive | Enforcement |
|-----------|-------------|
| 100% async (asyncio) | All new pipeline code must be async; CLI uses asyncio.run() at top level only |
| Local First via Ollama | No cloud APIs; orchestrator uses local qwen3.5:32b |
| Max 2 models loaded | Pipeline loads orchestrator, unloads, then worker loads later (Phase 6). Sequential. |
| Memory Safety (psutil) | ResourceGovernor already handles this; seed injection is single-call, low memory risk |
| Python 3.11+ strict typing | All new modules use `from __future__ import annotations`, type hints throughout |
| uv package manager | All test/run commands via `uv run` |
| pytest-asyncio | asyncio_mode = "auto" already configured |
| Frozen Pydantic models | SeedEvent, SeedEntity must use `frozen=True` |
| structlog component logging | New modules use `structlog.get_logger(component="seed")`, etc. |
| GSD Workflow Enforcement | Implementation through /gsd:execute-phase |

## Sources

### Primary (HIGH confidence)
- Ollama Python `AsyncClient.chat()` signature -- verified locally via `inspect.signature()` on installed ollama 0.6.1
- Existing codebase: `parsing.py`, `graph.py`, `config.py`, `ollama_client.py`, `ollama_models.py`, `worker.py` -- read directly
- [Ollama Structured Outputs docs](https://docs.ollama.com/capabilities/structured-outputs) -- format parameter usage
- [Ollama Thinking docs](https://docs.ollama.com/capabilities/thinking) -- think parameter usage

### Secondary (MEDIUM confidence)
- [Ollama Structured Outputs blog](https://ollama.com/blog/structured-outputs) -- Pydantic model_json_schema() pattern
- [GitHub Issue #10538](https://github.com/ollama/ollama/issues/10538) -- think + format incompatibility confirmed by maintainers
- [GitHub Issue #235 (ollama-js)](https://github.com/ollama/ollama-js/issues/235) -- format="json" disables thinking
- [GitHub Issue #10929](https://github.com/ollama/ollama/issues/10929) -- thinking mode produces invalid JSON with structured output

### Tertiary (LOW confidence)
- Whether Ollama 0.18.1 has partial fix for think+format -- no release notes verified; treat as still incompatible

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and integrated; versions verified from pip
- Architecture: HIGH -- all patterns exist in codebase; Phase 5 composes existing components
- Pitfalls: HIGH -- think+format incompatibility verified via multiple GitHub issues and official docs
- Persona prompts: MEDIUM -- quality of expanded prompts and modifiers is empirical; validated in Phase 6

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable domain; Ollama think+format fix may land sooner)
