# Phase 5: Seed Injection and Agent Personas - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-25
**Phase:** 05-seed-injection-and-agent-personas
**Areas discussed:** SeedEvent schema, Orchestrator prompting, Persona prompt depth, CLI entry point

---

## SeedEvent Schema

### Entity Detail Level

| Option | Description | Selected |
|--------|-------------|----------|
| Names + type only | Each entity is a name and category. Lightweight, reliable. | |
| Names + type + relevance score | Add 0.0-1.0 relevance score per entity for attention weighting. | ✓ |
| Rich entity objects | Name, type, relevance, relationship, context snippet. Maximum structure. | |

**User's choice:** Names + type + relevance score
**Notes:** None

### Sentiment Cue Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single overall sentiment | One score + summary for the whole rumor. | |
| Per-entity sentiment | Each entity gets its own sentiment score and cue. | ✓ |
| Categorical labels | Enum labels (bullish/bearish/neutral/mixed) instead of numeric. | |

**User's choice:** Per-entity sentiment
**Notes:** None

### Raw Text Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, raw + structured | SeedEvent contains both original rumor and extracted entities. | ✓ |
| Structured only | SeedEvent is purely extraction output; raw lives on Cycle node. | |

**User's choice:** Yes, raw + structured
**Notes:** None

### Entity Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, as Entity nodes | Create (:Entity) nodes linked to Cycle for graph-native queries. | ✓ |
| No, JSON property on Cycle | Store as JSON property on existing Cycle node. | |

**User's choice:** Yes, as Entity nodes
**Notes:** None

---

## Orchestrator Prompting

### LLM Mode

| Option | Description | Selected |
|--------|-------------|----------|
| Chat mode with JSON format | Use OllamaClient.chat() with format="json". Consistent with worker pattern. | ✓ |
| Generate mode with schema prompt | Use OllamaClient.generate() with schema in prompt. | |

**User's choice:** Chat mode with JSON format
**Notes:** None

### Thinking Mode

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, thinking enabled | High Reasoning mode per Phase 2 CONTEXT.md. Better extraction quality. | ✓ |
| No, thinking disabled | Faster but potentially lower quality. | |
| You decide | Let Claude determine based on quality. | |

**User's choice:** Yes, thinking enabled
**Notes:** None

### Parse Function

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, parse_seed_event() | Dedicated function in parsing.py with 3-tier fallback. | ✓ |
| Inline in pipeline | Parse directly in seed injection function. | |
| You decide | Let Claude choose. | |

**User's choice:** Yes, parse_seed_event()
**Notes:** None

### Model Lifecycle

| Option | Description | Selected |
|--------|-------------|----------|
| Managed within pipeline | Pipeline loads/unloads orchestrator model. Self-contained. | ✓ |
| Externally managed | Caller manages model lifecycle. | |

**User's choice:** Managed within pipeline
**Notes:** None

---

## Persona Prompt Depth

### Prompt Richness

| Option | Description | Selected |
|--------|-------------|----------|
| Medium — personality + heuristics | ~150-250 words with decision heuristics, biases, tone. | ✓ |
| Minimal — keep current + formatting | ~50 words + JSON formatting instructions. | |
| Deep — full character sheets | 300-500 words with backstory, strategies, triggers. | |

**User's choice:** Medium — personality + heuristics
**Notes:** None

### Intra-Bracket Variation

| Option | Description | Selected |
|--------|-------------|----------|
| Identical per bracket | All agents in a bracket share the same prompt. | |
| Slight variation per agent | Each agent gets a personality modifier within their archetype. | ✓ |
| You decide | Let Claude determine. | |

**User's choice:** Slight variation per agent
**Notes:** None

### Variation Method

| Option | Description | Selected |
|--------|-------------|----------|
| Predefined modifier pool | 3-5 modifiers per bracket, round-robin assigned. Deterministic. | ✓ |
| LLM-generated at init | Orchestrator generates unique modifiers. Non-deterministic. | |
| Template with index-based traits | Agent index deterministically selects traits from matrix. | |

**User's choice:** Predefined modifier pool
**Notes:** None

### JSON Formatting Instructions

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, in system prompt | Each prompt ends with expected output schema instructions. | ✓ |
| No, rely on format="json" | Let Ollama JSON mode handle formatting. | |
| You decide | Let Claude determine. | |

**User's choice:** Yes, in system prompt
**Notes:** None

---

## CLI Entry Point

### Rumor Input Method

| Option | Description | Selected |
|--------|-------------|----------|
| CLI argument string | Pass rumor as quoted string argument. | ✓ |
| Interactive prompt | Run command and get prompted to type rumor. | |
| File path option | Pass file containing the rumor. | |

**User's choice:** CLI argument string
**Notes:** None

### CLI Output

| Option | Description | Selected |
|--------|-------------|----------|
| Structured summary | Print cycle_id, entities with relevance/sentiment, overall sentiment. | ✓ |
| JSON dump | Full SeedEvent as JSON to stdout. | |
| Minimal — cycle ID only | Just the cycle_id for scripting. | |

**User's choice:** Structured summary
**Notes:** None

### CLI Location

| Option | Description | Selected |
|--------|-------------|----------|
| Extend __main__.py | Add inject subcommand to existing entry point. | |
| New cli.py module | Create cli.py with subcommand routing. __main__.py becomes shim. | ✓ |
| You decide | Let Claude choose. | |

**User's choice:** New cli.py module
**Notes:** None

---

## Claude's Discretion

- SeedEvent Pydantic model field ordering and validation constraints
- EntityType enum values and naming
- Orchestrator system prompt wording for entity extraction
- Specific personality modifier pool for each bracket
- CLI argument parser library choice
- Neo4j Entity node index definitions
- Graph relationship naming
- Output formatting details

## Deferred Ideas

None — discussion stayed within phase scope
