# Phase 1: Project Foundation - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning
**Source:** User input during plan-phase

<domain>
## Phase Boundary

Phase 1 delivers the runnable project scaffold: uv project setup, Pydantic configuration system, all type definitions (AgentPersona, SeedEvent, AgentDecision, BracketType), structured logging with per-agent correlation, and the 100 agent persona definitions across 10 brackets. This is the foundation every subsequent phase builds on.

</domain>

<decisions>
## Implementation Decisions

### Design Pillars (Mandatory)

1. **Adaptive Resource Management:** Implementation must use a `ResourceGovernor` class. It should wrap an `asyncio.Semaphore` and use `psutil` to dynamically shrink/grow the concurrent request slots based on a 90% memory pressure ceiling. (Note: Full ResourceGovernor implementation is Phase 3 — Phase 1 establishes the type stubs and interface contracts.)

2. **Decoupled UI Rendering:** In `ui.py`, use a snapshot-based rendering loop (200ms ticks) that reads from a shared state dictionary. Do not allow individual agent updates to trigger UI refreshes; the TUI must be the "observer." (Note: Full TUI implementation is Phase 9 — Phase 1 establishes the StateStore interface and shared state contract.)

3. **Modular Entry Point:** `main.py` must initialize the ResourceGovernor, the Neo4j driver, and the Textual app as global singletons (or via a clean AppState container) to prevent circular imports as we scale to 100 agents.

### Scope Constraints
- Focus strictly on environment setup, dependency management (uv/pyproject.toml), and the type/config foundation
- Do NOT start Miro logic
- Do NOT implement actual inference, graph queries, or TUI rendering — only interfaces and contracts

### Claude's Discretion
- Project directory structure and module organization
- Pydantic model field names and validation rules beyond what's specified in requirements
- structlog configuration details (processors, output format)
- Which bracket attributes to include in persona definitions beyond the basics (name, count, risk_profile, temperature, system_prompt_template, influence_weight_base)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — CONF-01, CONF-02, INFRA-11 requirements
- `.planning/ROADMAP.md` — Phase 1 success criteria and dependencies
- `.planning/research/SUMMARY.md` — Stack recommendations, corrected model tags
- `.planning/research/STACK.md` — Full technology stack with versions
- `.planning/research/ARCHITECTURE.md` — Component boundaries and data flow
- `CLAUDE.md` — Project-specific guidelines and constraints

</canonical_refs>

<specifics>
## Specific Ideas

- Use `uv` for package management with `pyproject.toml`
- Models: `qwen3:32b` (orchestrator), `qwen3.5:4b` (workers) — corrected from original spec
- All 10 brackets: Quants (10), Degens (20), Sovereigns (10), Macro (10), Suits (10), Insiders (10), Agents (15), Doom-Posters (5), Policy Wonks (5), Whales (5)
- AppState container pattern preferred over scattered global singletons

</specifics>

<deferred>
## Deferred Ideas

- ResourceGovernor full implementation (Phase 3)
- Neo4j connection and schema (Phase 4)
- TUI full rendering (Phase 9)
- Miro batcher (Phase 8)

</deferred>

---

*Phase: 01-project-foundation*
*Context gathered: 2026-03-24 via user input*
