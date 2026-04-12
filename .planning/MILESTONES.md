# Milestones

## v4.0 Interactive Simulation & Analysis (Shipped: 2026-04-12)

**Phases completed:** 4 phases (24-28), 13 plans

**Milestone Stats:**
- Timeline: 2026-04-09 → 2026-04-12 (4 days)
- Files changed: 143 files, 11,373 insertions
- Codebase: ~9,500 LOC Python (src/alphaswarm/)
- Test suite: 530+ tests

**Key accomplishments:**

- HTML report export — `assemble_html()`, pygal SVG charts with TUI dark theme, `--format html` CLI flag, full self-contained HTML simulation report
- Schwab portfolio overlay — CSV parser/bridge, `--portfolio` CLI flag, portfolio impact HTML section, `pre_seeded_observations` in `ReportEngine`
- Mid-simulation shock injection — `ResourceGovernor.suspend()/resume()` with memory-pressure guard, `ShockInputScreen` modal overlay, `StateStore` shock bridge, `write_shock_event` Neo4j persistence, `_collect_inter_round_shock` wiring with nested try/finally
- Shock impact analysis — `read_shock_event`/`read_shock_impact` Cypher inner-join methods, `_aggregate_shock_impact` pivot/held-firm computation, `BracketPanel` delta mode, `11_shock_impact.j2` Jinja2 template, CLI pre-seeding
- Simulation replay — `SimulationPhase.REPLAY`, `ReplayStore` no-drain semantics, 4 graph read methods, `CyclePickerScreen` overlay, full TUI replay mode with 3s auto-advance timer, `alphaswarm replay` CLI subcommand — all 7 human-verified scenarios pass

---

## v2.0 Engine Depth (Shipped: 2026-04-12)

**Phases completed:** 5 phases, 11 plans, 24 tasks

**Key accomplishments:**

- FlipType enum (7 transitions), EpisodeRecord frozen dataclass, WriteBuffer with drop-oldest asyncio queue, and compute_flip_type with full edge-case coverage
- 4 new GraphStateManager methods (write_rationale_episodes, write_narrative_edges, read_cycle_entities, write_decision_narratives) + write_decisions refactor returning list[str] with optional pre-generated IDs + RationaleEpisode composite index
- WriteBuffer wired into run_simulation() with 3x flush-per-round, RoundDispatchResult returning peer_contexts, post-simulation narrative generation via governor, and Cypher integration tests proving complete 3-round reasoning arc queryable
- Post node graph layer with write_posts (PARSE_ERROR filtering), read_ranked_posts (influence-weighted with coalesce fallback), write_read_post_edges (audit trail), and 15 new tests
- RankedPost-based _format_peer_context with 4000-char budget, write_posts/read_ranked_posts/write_read_post_edges wired into all 3 rounds of run_simulation, 13 new tests
- ParsedModifiersResult type, sanitize_entity_name helper, 3-tier parse_modifier_response, and generate_personas with optional modifiers kwarg -- 18 new tests green
- generate_modifiers() orchestrator call, inject_seed modifier callback, run_simulation wiring with persona regeneration -- all 3 rounds use entity-aware modifiers, 480 tests green
- InterviewContext/RoundDecision dataclasses with Neo4j graph read method and InterviewEngine with 10-pair sliding window, summary generation, and JSON instruction stripping
- InterviewScreen overlay with RichLog transcript, AgentCell click gating on COMPLETE phase, cycle_id capture, and @work-decorated async LLM messaging
- ReACT report engine with prompt-based tool dispatching (3 termination modes) and 8 Neo4j Cypher query tools covering all post-simulation analysis dimensions
- Jinja2 template rendering + aiofiles export + CLI report subcommand + TUI sentinel polling wired end-to-end from ReACT observations to markdown file and footer path display

---
