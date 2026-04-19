# Phase 6: Round 1 Standalone - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 06-round-1-standalone
**Areas discussed:** Invocation flow, Agent prompt, Result reporting, Simulation state

---

## Invocation Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Unified `run` command | Single `alphaswarm run "rumor"` does inject + round1 end-to-end. One command, full pipeline. | ✓ |
| Separate `round1` command | `inject` returns cycle_id, then `round1 <cycle_id>` runs inference separately. Decoupled. | |
| Both commands | Offer `run` for end-to-end AND `round1 <cycle_id>` for existing cycles. | |

**User's choice:** Unified `run` command
**Notes:** User initially asked whether invocation should be from a TUI rather than CLI. Clarified that the TUI is Phases 9-10 — the headless engine uses CLI entry points for now. User confirmed CLI approach makes sense.

---

## Agent Prompt

| Option | Description | Selected |
|--------|-------------|----------|
| Raw rumor only | Agents get the natural-language rumor as-is. Persona system prompts provide archetype biases. More realistic — traders hear rumors, not structured data. | ✓ |
| Structured SeedEvent context | Agents get raw rumor PLUS parsed entities, relevance scores, and sentiment. More informed but reduces diversity. | |
| You decide | Claude picks based on simulation diversity goals. | |

**User's choice:** Raw rumor only
**Notes:** None — straightforward selection.

---

## Result Reporting

| Option | Description | Selected |
|--------|-------------|----------|
| Bracket summary | Compact bracket-level table with signal counts and avg confidence. | |
| Bracket + top movers | Bracket table plus "Notable Decisions" section with top 5 highest-confidence agents and rationale snippets. | ✓ |
| Full per-agent dump | Every agent's decision printed. Comprehensive but noisy. | |

**User's choice:** Bracket + top movers
**Notes:** None — straightforward selection.

---

## Simulation State

| Option | Description | Selected |
|--------|-------------|----------|
| Neo4j only | Completion implicit from Decision node count. No in-memory state machine yet. | ✓ |
| SharedStateStore tracking | Write SimulationPhase transitions to SharedStateStore during pipeline. | |
| Both Neo4j + StateStore | Decisions in Neo4j (truth) + StateStore phase transitions (for future TUI). | |

**User's choice:** Neo4j only
**Notes:** SimulationPhase enum already exists — available for Phase 7 state machine, not wired in Phase 6.

---

## Claude's Discretion

- Internal pipeline function structure
- Worker model loading strategy within the pipeline
- Bracket table formatting details
- Top-5 selection logic
- Error handling for partial wave failures
- Progress indicators during wave dispatch

## Deferred Ideas

None — discussion stayed within phase scope
