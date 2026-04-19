# Phase 13: Dynamic Persona Generation - Research

**Researched:** 2026-04-01
**Domain:** LLM-driven modifier generation, JSON parsing, input sanitization, persona pipeline integration
**Confidence:** HIGH

## Summary

Phase 13 extends the existing persona generation pipeline to produce situation-aware agent modifiers. The orchestrator LLM (already loaded for seed parsing) generates 10 entity-specific bracket modifier strings in a single JSON call, replacing the static `BRACKET_MODIFIERS` round-robin system with one generated modifier per bracket per run. The existing `generate_personas()` function in `config.py` (line 441) assembles system prompts using `\nYou are a {modifier}.\n` -- Phase 13 replaces the static modifier source while preserving this exact insertion pattern.

The implementation follows three well-established codebase patterns: (1) the `parse_seed_event()` multi-tier JSON fallback in `parsing.py`, (2) the orchestrator chat call pattern in `seed.py` with `format="json"` and `think=True`, and (3) the frozen dataclass result container pattern (`ParsedSeedResult`). No new infrastructure is required -- this phase reuses the existing Ollama client, structlog logger, and Pydantic validation patterns.

The primary risk is prompt injection via adversarial entity names in the seed rumor. The CONTEXT.md specifies a `sanitize_entity_name()` function that truncates to 100 characters and strips Unicode Cc/Cf control characters while preserving standard punctuation. Python's built-in `unicodedata` module provides the `category()` function needed for this, requiring no additional dependencies.

**Primary recommendation:** Implement as a single `generate_modifiers()` async function in `config.py` that makes one orchestrator chat call, parses the JSON response with the established multi-tier fallback, and returns a `ParsedModifiersResult` dataclass. Integrate by calling it in `run_simulation()` between `inject_seed()` return and `generate_personas()`, passing generated modifiers to `generate_personas()` via a new optional parameter.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Replace static `BRACKET_MODIFIERS` -- orchestrator generates one new modifier string per bracket (10 total) incorporating entity context. Generated modifier replaces the static one, no augmentation.
- **D-02:** One modifier per bracket per simulation run. All agents in same bracket share one entity-aware modifier.
- **D-03:** Modifier slot in `generate_personas()` unchanged: `\nYou are a {modifier}.\n`. Generated string replaces static modifier at this exact insertion point.
- **D-04:** Inputs to orchestrator: all extracted entities (full `SeedEntity` list) PLUS original `raw_rumor` text from `SeedEvent`.
- **D-05:** Output JSON: flat dict keyed by bracket name (BracketType enum values, lowercase): `{"quants": "modifier string", ..., "whales": "modifier string"}`. Exactly 10 keys required.
- **D-06:** Single JSON-mode inference call, same session as seed parsing. Multi-tier parse fallback follows `parse_seed_event()` pattern.
- **D-07:** Full failure fallback: log structured warning, fall back to static `BRACKET_MODIFIERS` for all brackets. Simulation proceeds.
- **D-08:** Partial failure: per-bracket fallback -- use generated modifier where valid, static for missing/malformed. Log warning per bracket.
- **D-09:** `ParsedModifiersResult` dataclass with `modifiers: dict[BracketType, str]` and `parse_tier: int`.
- **D-10:** Sanitization at injection time -- before entity data interpolated into orchestrator prompt. `SeedEntity.name` remains unmodified.
- **D-11:** Sanitization rules: truncate 100 chars, strip Cc and Cf Unicode categories. Preserve standard punctuation (hyphens, periods, apostrophes, ampersands, parentheses).
- **D-12:** `sanitize_entity_name(name: str) -> str` helper function. Called per entity before constructing prompt. No sanitization on `raw_rumor`.

### Claude's Discretion
- Specific system prompt design for modifier generation orchestrator call
- Multi-tier JSON parse implementation (may reuse parse utilities from Phase 05)
- Whether `generate_modifiers()` lives in `config.py` or `simulation.py`
- Where in `cli.py` or `run_simulation()` the modifier generation call is inserted
- Character length limit for generated modifier strings (recommendation: 150-char cap)
- Whether modifier generation reuses orchestrator async session or opens fresh one

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERSONA-01 | Orchestrator LLM generates entity-specific bracket modifiers from SeedEvent entities in a single JSON call | Orchestrator chat pattern from `seed.py` (line 58), JSON format mode, multi-tier parse fallback from `parsing.py` (line 166). D-04 through D-06 specify exact input/output schema. |
| PERSONA-02 | Entity-aware modifiers injected into generate_personas() pipeline, preserving 10-bracket structure and 100-agent count | `generate_personas()` at config.py:441 uses `BRACKET_MODIFIERS` dict (line 101) with round-robin. Phase 13 replaces source but preserves insertion pattern `\nYou are a {modifier}.\n` at line 463. D-01 through D-03 lock the integration approach. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `unicodedata` | stdlib | Unicode category detection for Cc/Cf character stripping | Built-in, no dependency; `unicodedata.category(c)` returns 2-char category code |
| `ollama` | >=0.6.1 | Orchestrator LLM chat call with `format="json"` | Already in use for seed parsing in `seed.py` |
| `pydantic` | >=2.12.5 | Validation of BracketType enum keys in parsed response | Already used throughout for frozen models |
| `structlog` | >=25.5.0 | Component-scoped logging for warnings on fallback events | Already used with `component="parsing"` pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` | stdlib | JSON parsing in multi-tier fallback | Tier 1 parse attempt |
| `re` | stdlib | Code-fence stripping, JSON block extraction | Tier 2 parse fallback |
| `dataclasses` | stdlib | `ParsedModifiersResult` frozen dataclass | Result container matching `ParsedSeedResult` pattern |

### Alternatives Considered
No alternatives needed -- this phase uses exclusively existing stack components with no new dependencies.

**Installation:**
No new packages required.

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    config.py          # generate_personas() modified to accept optional modifiers param
                       # generate_modifiers() async function added
                       # sanitize_entity_name() helper added
                       # MODIFIER_GENERATION_PROMPT constant added
                       # ParsedModifiersResult dataclass added to types.py
    types.py           # ParsedModifiersResult frozen dataclass
    parsing.py         # parse_modifier_response() with multi-tier fallback (or inline in config.py)
    simulation.py      # Integration: call generate_modifiers() between inject_seed() and generate_personas()
    seed.py            # Unchanged -- inject_seed() returns ParsedSeedResult as before
    cli.py             # All 3 generate_personas() call sites updated to pass modifiers
```

### Pattern 1: Orchestrator Chat Call (Reuse from seed.py)
**What:** Single async chat call to orchestrator LLM with `format="json"` and `think=True`
**When to use:** Generating the 10 bracket modifiers from SeedEvent entities
**Example:**
```python
# Source: src/alphaswarm/seed.py lines 57-66
response = await ollama_client.chat(
    model=orchestrator_alias,
    messages=[
        {"role": "system", "content": MODIFIER_GENERATION_PROMPT},
        {"role": "user", "content": user_message_with_entities},
    ],
    format="json",
    think=True,
)
```

### Pattern 2: Multi-Tier JSON Parse Fallback (Reuse from parsing.py)
**What:** 3-tier fallback: direct JSON parse -> code-fence strip/regex -> fallback to static
**When to use:** Parsing the orchestrator's modifier response
**Example:**
```python
# Source: src/alphaswarm/parsing.py lines 166-215
# Tier 1: json.loads(raw) -> validate keys
# Tier 2: _strip_code_fences(raw) -> _JSON_BLOCK_RE.search -> validate
# Tier 3: Return static BRACKET_MODIFIERS fallback with parse_tier=3
```

### Pattern 3: Frozen Dataclass Result Container
**What:** `ParsedModifiersResult` mirrors `ParsedSeedResult` pattern
**When to use:** Returning modifier generation results with observability metadata
**Example:**
```python
# Source: src/alphaswarm/types.py lines 96-112
@dataclasses.dataclass(frozen=True)
class ParsedModifiersResult:
    modifiers: dict[BracketType, str]
    parse_tier: int  # 1=direct, 2=extracted, 3=full fallback
```

### Pattern 4: Entity Name Sanitization
**What:** Strip Unicode control characters (Cc, Cf) and truncate to 100 chars
**When to use:** Before interpolating entity names into the modifier generation prompt
**Example:**
```python
# Source: Python unicodedata stdlib
import unicodedata

def sanitize_entity_name(name: str) -> str:
    truncated = name[:100]
    return "".join(
        c for c in truncated
        if unicodedata.category(c) not in ("Cc", "Cf")
    )
```

### Anti-Patterns to Avoid
- **Raw entity string concatenation into prompts:** Never interpolate `SeedEntity.name` directly into system prompts without sanitization. Always call `sanitize_entity_name()` first.
- **Mutating SeedEntity.name:** Sanitize at prompt-construction time only. The original `SeedEntity.name` must remain intact for graph writes and TUI display (per D-10, confirmed in Phase 11 CONTEXT).
- **Multiple orchestrator calls:** D-06 locks this to a single JSON-mode call. Do not make per-bracket calls.
- **Modifying BRACKET_MODIFIERS dict:** The static dict serves as the fallback source. It must remain unchanged at module level.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unicode control character detection | Custom char-code ranges | `unicodedata.category(c)` | Covers full Unicode spec, not just ASCII control chars |
| JSON extraction from LLM output | New regex patterns | Existing `_strip_code_fences()` and `_JSON_BLOCK_RE` from `parsing.py` | Already battle-tested across 477 test runs |
| Multi-tier parse fallback | New fallback framework | Follow `parse_seed_event()` pattern exactly | Proven pattern with tier observability |
| BracketType enum validation | Manual string matching | `BracketType(key)` enum constructor | Raises ValueError on invalid keys automatically |

**Key insight:** Phase 13 introduces no novel patterns. Every component has an existing template in the codebase. The risk is in the integration wiring, not in any individual component.

## Common Pitfalls

### Pitfall 1: Orchestrator Model Lifecycle Collision
**What goes wrong:** `generate_modifiers()` tries to call the orchestrator after `inject_seed()` has already unloaded it (seed.py line 102: `finally: await model_manager.unload_model()`).
**Why it happens:** `inject_seed()` self-manages its orchestrator model lifecycle with a try/finally that always unloads.
**How to avoid:** Either (a) call `generate_modifiers()` INSIDE `inject_seed()` before the finally block unloads the model, returning modifiers alongside ParsedSeedResult, or (b) reload the orchestrator model in `generate_modifiers()`. Option (a) is strongly preferred -- avoids a 30-second model reload penalty and matches D-06 ("same session as seed parsing").
**Warning signs:** `OllamaInferenceError` on the modifier generation call with "model not found" or timeout.

### Pitfall 2: Partial Key Validation Gaps
**What goes wrong:** The LLM returns JSON with 8/10 bracket keys, but the missing keys are not detected because validation only checks `isinstance(data, dict)`.
**Why it happens:** LLMs can omit keys, especially for less common brackets like `doom_posters` or `policy_wonks`.
**How to avoid:** After parsing, iterate all 10 `BracketType` enum values. For each missing/invalid key, apply per-bracket fallback from static `BRACKET_MODIFIERS` (D-08). Log each fallback bracket.
**Warning signs:** Agents in some brackets getting empty modifier lines or generic prompts.

### Pitfall 3: generate_personas() Call Sites Divergence
**What goes wrong:** `generate_personas(brackets)` is called in 4 places (cli.py lines 54, 538, 568, 604). Updating only the `run_simulation` path leaves the banner, inject, and TUI paths generating static personas.
**Why it happens:** Multiple CLI entry points each construct their own persona lists.
**How to avoid:** The banner (`_print_banner`) and inject (`_handle_inject`) paths do NOT need dynamic modifiers -- they run before any simulation. Only `_handle_run` and `_handle_tui` paths feed into `run_simulation()`. The key integration point is inside `run_simulation()` itself, which receives pre-built personas. The cleanest approach: call `generate_modifiers()` inside `run_simulation()` after `inject_seed()` returns the SeedEvent, then call `generate_personas(brackets, modifiers=modifiers)` with the new optional parameter.
**Warning signs:** Static modifier text appearing in agent system prompts during simulation (check logs).

### Pitfall 4: Modifier String Length Explosion
**What goes wrong:** The LLM generates verbose 200+ word modifier strings that bloat system prompts past the 350-word safety cap.
**Why it happens:** Without explicit length constraints in the prompt, LLMs tend to elaborate.
**How to avoid:** (1) Prompt instructs "8-20 words per modifier" with examples. (2) Validate response: truncate any modifier exceeding the cap (150 chars recommended) at word boundary. (3) Existing test `test_persona_word_count_under_350` catches overflow.
**Warning signs:** `test_persona_word_count_under_350` test failures.

### Pitfall 5: BracketType Enum Case Mismatch
**What goes wrong:** LLM returns keys like `"Quants"` or `"QUANTS"` instead of `"quants"`.
**Why it happens:** LLMs don't reliably maintain case conventions even with explicit instructions.
**How to avoid:** Lowercase all dict keys before validation: `{k.lower(): v for k, v in data.items()}`. Then validate against BracketType enum values.
**Warning signs:** All 10 brackets falling back to static modifiers despite LLM producing valid content.

### Pitfall 6: Existing Test Breakage
**What goes wrong:** `test_bracket_modifiers_count_range` (test_personas.py:131) expects 3-5 modifiers per bracket. If `BRACKET_MODIFIERS` structure changes, this test fails.
**Why it happens:** Phase 13 does NOT change the static `BRACKET_MODIFIERS` dict -- it remains as the fallback. But if the generate_personas signature changes, tests using the `all_personas` fixture (which calls `generate_personas(load_bracket_configs())` with no modifiers) must still pass with static fallback behavior.
**How to avoid:** Make the new `modifiers` parameter optional with `None` default. When `None`, `generate_personas()` falls back to existing round-robin from `BRACKET_MODIFIERS`. All existing tests pass unchanged.
**Warning signs:** Existing persona test failures after signature change.

## Code Examples

### Entity Sanitization Function
```python
# New function in config.py (or utils.py)
import unicodedata

def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name for safe prompt interpolation (D-11, D-12).

    Truncates to 100 characters and strips Unicode Cc (control) and
    Cf (format) categories. Preserves standard punctuation including
    hyphens, periods, apostrophes, ampersands, and parentheses.
    """
    truncated = name[:100]
    return "".join(
        c for c in truncated
        if unicodedata.category(c) not in ("Cc", "Cf")
    )
```

### Modifier Generation Prompt Construction
```python
# Build user message with sanitized entities
def _build_modifier_user_message(seed_event: SeedEvent) -> str:
    """Build the user message for modifier generation from SeedEvent (D-04)."""
    entity_lines = []
    for e in seed_event.entities:
        safe_name = sanitize_entity_name(e.name)
        entity_lines.append(
            f"- {safe_name} (type: {e.type.value}, "
            f"relevance: {e.relevance:.2f}, sentiment: {e.sentiment:+.2f})"
        )
    entities_block = "\n".join(entity_lines) if entity_lines else "(no entities extracted)"

    return (
        f"SEED RUMOR:\n{seed_event.raw_rumor}\n\n"
        f"EXTRACTED ENTITIES:\n{entities_block}"
    )
```

### ParsedModifiersResult Dataclass
```python
# In types.py, following ParsedSeedResult pattern
@dataclasses.dataclass(frozen=True)
class ParsedModifiersResult:
    """Result of modifier generation with parse-tier observability (D-09).

    parse_tier values:
      1 = Direct JSON parse succeeded with all 10 keys
      2 = Code-fence strip / regex extraction succeeded
      3 = Full fallback to static BRACKET_MODIFIERS
    """
    modifiers: dict[BracketType, str]
    parse_tier: int
```

### Modified generate_personas Signature
```python
# In config.py -- backward-compatible signature change
def generate_personas(
    brackets: list[BracketConfig],
    *,
    modifiers: dict[BracketType, str] | None = None,
) -> list[AgentPersona]:
    """Generate all agent personas from bracket definitions.

    When modifiers is provided, uses the generated modifier for each bracket.
    When modifiers is None, falls back to static BRACKET_MODIFIERS round-robin.
    """
    validate_bracket_counts(brackets)
    personas: list[AgentPersona] = []
    for bracket in brackets:
        if modifiers is not None and bracket.bracket_type in modifiers:
            # Phase 13: single generated modifier for all agents in bracket
            modifier = modifiers[bracket.bracket_type]
        else:
            # Fallback: static round-robin (original behavior)
            static_mods = BRACKET_MODIFIERS.get(bracket.bracket_type, [])
            modifier = ""  # set per-agent below
        for i in range(1, bracket.count + 1):
            agent_id = f"{bracket.bracket_type.value}_{i:02d}"
            agent_name = f"{bracket.display_name} {i}"
            if modifiers is None or bracket.bracket_type not in modifiers:
                modifier = static_mods[(i - 1) % len(static_mods)] if static_mods else ""
            modifier_line = f"\nYou are a {modifier}.\n" if modifier else ""
            system_prompt = (
                f"[{agent_name} | {bracket.display_name} bracket]\n"
                f"{bracket.system_prompt_template}"
                f"{modifier_line}"
                f"{JSON_OUTPUT_INSTRUCTIONS}"
            )
            personas.append(AgentPersona(
                id=agent_id, name=agent_name, bracket=bracket.bracket_type,
                risk_profile=bracket.risk_profile, temperature=bracket.temperature,
                system_prompt=system_prompt,
                influence_weight_base=bracket.influence_weight_base,
            ))
    return personas
```

### Integration Point in run_simulation
```python
# In simulation.py, after inject_seed returns and before worker model loads
# (inside run_round1 or extracted to run_simulation level)

# After: cycle_id, parsed_result = await inject_seed(...)
# Before: await model_manager.unload_model(orchestrator_alias)

# Generate modifiers while orchestrator is still loaded
modifier_result = await generate_modifiers(
    seed_event=parsed_result.seed_event,
    ollama_client=ollama_client,
    model_alias=orchestrator_alias,
)
logger.info(
    "modifier_generation_complete",
    parse_tier=modifier_result.parse_tier,
    generated_count=sum(1 for _ in modifier_result.modifiers),
)
# Then pass modifiers to generate_personas
personas = generate_personas(brackets, modifiers=modifier_result.modifiers)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `BRACKET_MODIFIERS` round-robin (4-5 per bracket) | Single LLM-generated modifier per bracket per run | Phase 13 | Agents get situation-aware modifiers; fallback preserves old behavior |
| Hardcoded persona diversity | Entity-driven persona diversity | Phase 13 | Quants analyzing "EV market share dynamics" vs generic "low-volatility strategies" |
| No input sanitization on entity names | `sanitize_entity_name()` strips Cc/Cf, truncates to 100 chars | Phase 13 | Prevents prompt injection via adversarial seed rumor entity names |

## Open Questions

1. **Where exactly should `generate_modifiers()` be called relative to `inject_seed()`?**
   - What we know: The orchestrator model is loaded inside `inject_seed()` and unloaded in its `finally` block (seed.py:100-102). D-06 says "same session as seed parsing."
   - What's unclear: Whether to modify `inject_seed()` to also return modifiers, or to restructure the model lifecycle so the orchestrator stays loaded across both calls.
   - Recommendation: Extend `inject_seed()` to accept an optional `generate_modifiers_fn` callback that runs before the `finally` block, or refactor `inject_seed()` to return the orchestrator alias and let the caller manage the lifecycle. The planner should decide the exact integration approach.

2. **Modifier length cap -- exact value?**
   - What we know: CONTEXT.md suggests 150-char cap. Static modifiers average 8-15 words (~60-100 chars). The 350-word system prompt cap is enforced by tests.
   - What's unclear: Whether 150 chars is optimal or too restrictive for entity-rich domains.
   - Recommendation: Use 150-char cap with word-boundary truncation. If truncated, log a debug message. The prompt should instruct "8-20 words."

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_config.py tests/test_personas.py tests/test_parsing.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERSONA-01a | `sanitize_entity_name()` truncates at 100 chars | unit | `uv run pytest tests/test_config.py::test_sanitize_entity_name_truncation -x` | Wave 0 |
| PERSONA-01b | `sanitize_entity_name()` strips Cc/Cf control characters | unit | `uv run pytest tests/test_config.py::test_sanitize_entity_name_strips_control_chars -x` | Wave 0 |
| PERSONA-01c | `sanitize_entity_name()` preserves valid punctuation (S&P 500, Meta (Facebook)) | unit | `uv run pytest tests/test_config.py::test_sanitize_entity_name_preserves_punctuation -x` | Wave 0 |
| PERSONA-01d | `ParsedModifiersResult` frozen dataclass with correct fields | unit | `uv run pytest tests/test_seed.py::test_parsed_modifiers_result_construction -x` | Wave 0 |
| PERSONA-01e | Modifier parse: tier 1 direct JSON with 10 valid keys | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_tier1 -x` | Wave 0 |
| PERSONA-01f | Modifier parse: tier 2 code-fence wrapped JSON | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_tier2 -x` | Wave 0 |
| PERSONA-01g | Modifier parse: tier 3 full fallback to static | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_tier3_fallback -x` | Wave 0 |
| PERSONA-01h | Modifier parse: partial failure -- per-bracket fallback | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_partial_fallback -x` | Wave 0 |
| PERSONA-01i | Modifier parse: case-insensitive key normalization | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_case_insensitive -x` | Wave 0 |
| PERSONA-02a | `generate_personas()` with modifiers produces 100 agents | unit | `uv run pytest tests/test_personas.py::test_generate_personas_with_modifiers_count -x` | Wave 0 |
| PERSONA-02b | `generate_personas()` with modifiers uses generated modifier, not static | unit | `uv run pytest tests/test_personas.py::test_generate_personas_with_modifiers_content -x` | Wave 0 |
| PERSONA-02c | `generate_personas()` without modifiers (None) preserves original behavior | unit | `uv run pytest tests/test_personas.py::test_generate_personas_backward_compatible -x` | Wave 0 |
| PERSONA-02d | All existing persona tests pass with no changes | regression | `uv run pytest tests/test_personas.py -x -q` | Existing |
| PERSONA-02e | Modifier length cap enforced (truncation at word boundary) | unit | `uv run pytest tests/test_config.py::test_modifier_length_cap -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_config.py tests/test_personas.py tests/test_parsing.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green (477+ tests) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_config.py` -- add `test_sanitize_entity_name_*` tests (3 tests for truncation, Cc/Cf stripping, punctuation preservation)
- [ ] `tests/test_config.py` -- add `test_modifier_length_cap` test
- [ ] `tests/test_seed.py` -- add `test_parsed_modifiers_result_*` tests (construction, frozen, all tiers)
- [ ] `tests/test_parsing.py` -- add `test_parse_modifiers_*` tests (tier 1, tier 2, tier 3, partial fallback, case insensitive)
- [ ] `tests/test_personas.py` -- add `test_generate_personas_with_modifiers_*` tests (count, content, backward compatible)

## Project Constraints (from CLAUDE.md)

| Directive | Phase 13 Impact |
|-----------|-----------------|
| 100% async (asyncio) | `generate_modifiers()` must be async (uses `ollama_client.chat()`) |
| Local first via Ollama | Modifier generation uses local orchestrator model, no cloud APIs |
| Max 2 models simultaneously | Modifier generation happens while orchestrator is loaded for seed parsing; worker not yet loaded. No lifecycle conflict. |
| Python 3.11+ strict typing | All new functions must have full type annotations |
| `uv` package manager | No new dependencies to install |
| `pytest-asyncio` for tests | Async test functions auto-detected via `asyncio_mode = "auto"` |
| `structlog` for logging | Use `structlog.get_logger(component="config")` or appropriate component |
| Pydantic for validation | `ParsedModifiersResult` uses `dataclasses.dataclass(frozen=True)` to match `ParsedSeedResult` pattern |

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/config.py` -- `generate_personas()` (line 441), `BRACKET_MODIFIERS` (line 101), modifier insertion pattern (line 463)
- `src/alphaswarm/types.py` -- `BracketType` enum, `SeedEntity`, `SeedEvent`, `ParsedSeedResult` pattern
- `src/alphaswarm/parsing.py` -- `parse_seed_event()` multi-tier fallback (line 166), `_strip_code_fences()`, `_JSON_BLOCK_RE`
- `src/alphaswarm/seed.py` -- `inject_seed()` orchestrator lifecycle (lines 39-102), `ORCHESTRATOR_SYSTEM_PROMPT`
- `src/alphaswarm/simulation.py` -- `run_simulation()` (line 710), `run_round1()` (line 423) integration points
- `src/alphaswarm/cli.py` -- all `generate_personas()` call sites (lines 54, 538, 568, 604)
- [Python unicodedata documentation](https://docs.python.org/3/library/unicodedata.html) -- `category()` function for Cc/Cf detection
- `.planning/phases/13-dynamic-persona-generation/13-CONTEXT.md` -- all D-01 through D-12 decisions

### Secondary (MEDIUM confidence)
- [Unicode control character removal patterns](https://blog.finxter.com/how-to-remove-control-characters-from-a-string-in-python/) -- verified against Python docs
- [Unicode character categories](https://www.fileformat.info/info/unicode/category/index.htm) -- Cc = control, Cf = format category definitions

### Tertiary (LOW confidence)
None -- all findings verified against codebase and official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all patterns exist in codebase
- Architecture: HIGH -- follows established orchestrator call, parse fallback, and persona generation patterns exactly
- Pitfalls: HIGH -- all pitfalls derived from direct code analysis of actual call sites and model lifecycle

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable -- no dependency changes expected)
