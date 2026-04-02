# Phase 13: Dynamic Persona Generation - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 13 makes agent personas situation-specific by generating entity-aware bracket modifiers from the parsed SeedEvent in a single orchestrator LLM call, then injecting them into the existing `generate_personas()` pipeline. The 10-bracket structure and 100-agent count are invariant. No new TUI panels, no changes to inference or graph writes. No agent interview changes (Phase 14). No report changes (Phase 15).

</domain>

<decisions>
## Implementation Decisions

### Modifier Structure
- **D-01:** Replace static `BRACKET_MODIFIERS` — the orchestrator generates one new modifier string per bracket (10 total) that incorporates entity context. E.g., for a Tesla rumor, the Quants modifier becomes "quantitative analyst modeling EV market share dynamics" instead of the static "conservative quantitative analyst who favors low-volatility strategies." No augmentation — the generated modifier replaces the static one in the `generate_personas()` assembly.
- **D-02:** One modifier per bracket per simulation run. All agents in the same bracket share one entity-aware modifier for this run. (No round-robin variants — current BRACKET_MODIFIERS has 4–5 per bracket; Phase 13 produces 1 per bracket.)
- **D-03:** The modifier slot in `generate_personas()` is unchanged: `\nYou are a {modifier}.\n`. The generated string replaces the static modifier at this exact insertion point.

### LLM Output Schema (Orchestrator Call)
- **D-04:** Inputs to the orchestrator: all extracted entities (full `SeedEntity` list: name, type, relevance, sentiment) PLUS the original `raw_rumor` text from `SeedEvent`. Full context gives the LLM maximum signal for calibrating modifier tone.
- **D-05:** Output JSON structure: flat dict keyed by bracket name (BracketType enum values, lowercase): `{"quants": "modifier string", "degens": "modifier string", ..., "whales": "modifier string"}`. Exactly 10 keys required for a fully-valid response. Maps directly to BracketType enum values for validation.
- **D-06:** The orchestrator call is a single JSON-mode inference call — same session as seed parsing (orchestrator already loaded, avoids reload cost). Multi-tier parse fallback follows the same pattern as `parse_seed_event()` in Phase 05 (direct JSON parse → code-fence strip → regex extraction → fallback).

### Fallback Behavior
- **D-07:** Full failure (unparseable/empty response after all parse tiers): log a structured warning via structlog (component-scoped, same pattern as existing warning logs) and fall back to static `BRACKET_MODIFIERS` for all brackets. Simulation proceeds normally — degraded but not broken.
- **D-08:** Partial failure (some brackets present and valid, others missing or malformed): per-bracket fallback — use generated modifier where valid, fall back to static for the missing/malformed bracket. Maximum use of what the LLM produced. Log a warning for each bracket that fell back.
- **D-09:** A `ParsedModifiersResult` dataclass (analogous to `ParsedSeedResult`) should be returned from the modifier generation function, carrying `modifiers: dict[BracketType, str]` and `parse_tier: int` for observability. Parse tier: 1 = direct JSON, 2 = code-fence/regex extraction, 3 = full fallback to static.

### Sanitization
- **D-10:** Sanitization happens at injection time — immediately before entity data is interpolated into the orchestrator prompt for modifier generation. `SeedEntity.name` values remain unmodified (source-of-truth for graph writes, TUI display, entity references stays intact).
- **D-11:** Sanitization rules for entity names before injection: (1) truncate to 100 characters max; (2) strip non-printable and control characters (Unicode categories Cc and Cf, i.e., `\x00–\x1f`, `\x7f`, and invisible Unicode). Preserve standard punctuation including hyphens, periods, apostrophes, ampersands, and parentheses — real entity names like "S&P 500", "Berkshire Hathaway", "Meta (Facebook)" must remain intact.
- **D-12:** A `sanitize_entity_name(name: str) -> str` helper function is added. Called per entity before constructing the modifier-generation prompt. No sanitization is applied to the `raw_rumor` field (it goes into the prompt as-is, surrounded by a clearly labeled block to minimize injection risk).

### Claude's Discretion
- Specific system prompt design for the modifier generation orchestrator call (tone, instructions, format constraints)
- Multi-tier JSON parse implementation (may reuse parse utilities from Phase 05's seed parsing if they exist as shared helpers)
- Whether `generate_modifiers()` is a standalone function in `config.py` or lives in `simulation.py`
- Where in `cli.py` or `run_simulation()` the modifier generation call is inserted (must be after `parse_seed_event()` returns and before `generate_personas()` is called)
- Character length limit for generated modifier strings (recommendation: 150-char cap to prevent context bloat; planner decides exact cap)
- Whether modifier generation reuses the orchestrator's async session object or opens a fresh one

</decisions>

<specifics>
## Specific Ideas

- Generated modifier strings should follow the same stylistic register as existing static modifiers: short, first-person-adjacent descriptor, 8–20 words. E.g., static: "conservative quantitative analyst who favors low-volatility strategies" → generated: "quantitative analyst modeling EV supply chain disruption and margin compression."
- The `ParsedModifiersResult.parse_tier` field (D-09) mirrors `ParsedSeedResult.parse_tier` from Phase 05 — consistent observability pattern across all orchestrator parse operations.
- Bracket name keys in the returned JSON must exactly match BracketType enum values (`quants`, `degens`, `sovereigns`, `macro`, `suits`, `insiders`, `agents`, `doom_posters`, `policy_wonks`, `whales`) for direct enum-keyed validation.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — PERSONA-01 (orchestrator generates entity-specific bracket modifiers in single JSON call), PERSONA-02 (modifiers injected into generate_personas(), 10-bracket structure and 100-agent count preserved)
- `.planning/ROADMAP.md` — Phase 13 success criteria (3 criteria including sanitization requirement)

### Existing Implementation (Primary)
- `src/alphaswarm/config.py` — `generate_personas()` (line 441, function to modify), `BRACKET_MODIFIERS` (line 101, static dict being replaced/fallback), `DEFAULT_BRACKETS` (BracketConfig list with system_prompt_template per bracket), `JSON_OUTPUT_INSTRUCTIONS` (line 89, appended after modifier), `load_bracket_configs()` (line 425)
- `src/alphaswarm/types.py` — `SeedEntity` (name, type: EntityType, relevance, sentiment), `SeedEvent` (raw_rumor, entities, overall_sentiment), `ParsedSeedResult` (parse_tier pattern to follow), `BracketType` enum (keys for output dict validation)
- `src/alphaswarm/cli.py` — `generate_personas(brackets)` call sites (lines 54, 538, 568, 604 — integration points where modifier generation must be inserted before these calls)

### Prior Phase Context
- `.planning/phases/05-seed-injection-and-agent-personas/05-CONTEXT.md` — orchestrator model lifecycle, parse_seed_event() multi-tier fallback pattern to replicate for modifier generation
- `.planning/phases/11-live-graph-memory/11-CONTEXT.md` — SeedEntity usage in REFERENCES edges (confirms SeedEntity.name must remain unsanitized in the original struct)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `parse_seed_event()` in Phase 05 code — multi-tier JSON parse pattern (direct → code-fence strip → regex → fallback) is the established template for orchestrator output parsing; replicate for `generate_modifiers()`
- `BRACKET_MODIFIERS` dict (config.py:101) — serves as the fallback dict when modifier generation fails; structure is `dict[BracketType, list[str]]` (Phase 13 only needs one string per bracket, but fallback picks `[0]` from the list)
- `BracketType` enum — lowercase string values are the expected JSON keys from the orchestrator
- Structlog component-scoped logger pattern — use for warning logs on fallback events

### Established Patterns
- Frozen Pydantic models / frozen dataclasses for result containers (`ParsedSeedResult` pattern → `ParsedModifiersResult`)
- Session-per-method async orchestrator calls (Phase 05) — modifier generation follows same pattern
- `validate_bracket_counts()` defensive validation pattern — add analogous validation for returned modifier dict (check all 10 BracketType keys present)

### Integration Points
- `cli.py` — modifier generation inserted between `parse_seed_event()` return and each `generate_personas(brackets)` call
- `generate_personas(brackets)` signature — accepts `brackets: list[BracketConfig]` — will need an additional `modifiers: dict[BracketType, str] | None` parameter (or modifier generation happens in the caller before passing a patched brackets list — planner decides)

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-dynamic-persona-generation*
*Context gathered: 2026-04-01*
