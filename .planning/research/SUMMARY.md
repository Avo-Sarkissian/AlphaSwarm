# Project Research Summary

**Project:** AlphaSwarm v2.0 Engine Depth
**Domain:** Local-first multi-agent LLM financial simulation engine (feature expansion)
**Researched:** 2026-03-31
**Confidence:** HIGH

## Executive Summary

AlphaSwarm v2.0 expands a proven v1 simulation engine (10 phases shipped, fully operational) into a deeper analytical platform. The core challenge is not building the simulation -- it works -- but enriching it with post-simulation intelligence: living graph memory, conversational agent interviews, structured market reports, social influence dynamics, and entity-aware persona generation. All five features build on the same stack (Python 3.11+, asyncio, Ollama, Neo4j, Textual) with only two new dependencies needed (Jinja2 for report templates, aiofiles for non-blocking file writes). This is an incremental engineering problem, not a greenfield one.

The recommended approach is dependency-ordered: Live Graph Memory must ship first because every other v2 feature reads from the enriched Neo4j graph it creates. Post-simulation Report and Agent Interviews follow as the primary analytical outputs. Richer Agent Interactions and Dynamic Persona Generation then layer social dynamics and input quality onto the stable foundation. One critical finding shapes the entire implementation: Ollama native tool calling is broken for qwen3.5 models (confirmed GitHub issues #14493, #14745). The ReACT report agent must use prompt-based tool dispatching with Python-side parsing -- no framework dependency needed, approximately 100 lines of code.

The primary risk is M1 Max memory pressure and model lifecycle coordination in the post-simulation phase. Model swaps between the worker (qwen3.5:9b) and orchestrator (qwen3.5:32b) take approximately 30 seconds each and must be serialized. Interviews should use the worker model (already loaded post-simulation); reports use the orchestrator (requires model swap). Running both concurrently would cause queue starvation and must be prevented at the CLI/TUI level. All write patterns must use the existing batch UNWIND approach -- per-agent writes during simulation would increase Neo4j transactions 700x and cause connection pool exhaustion.

## Key Findings

### Recommended Stack

The v1 stack requires no major changes. Two libraries are additive: Jinja2 (>=3.1.6) for report section templating and aiofiles (>=24.1.0) for non-blocking markdown file export. Every framework-level alternative (LangChain, LlamaIndex, APOC, Zep Cloud, neo4j driver 6.x) was evaluated and rejected -- they add dependency weight or architectural impedance for capabilities already present in the existing codebase. The qwen3.5 tool calling bug is the only stack-level surprise: native `tools=` parameter support does not work and requires a prompt-based ReACT workaround.

**Core technologies:**
- **Python 3.11+ / asyncio:** 100% async runtime -- no blocking I/O on main event loop. All new components (InterviewEngine, ReportGenerator, PersonaGenerator) must respect this constraint.
- **ollama-python >=0.6.1:** Handles multi-turn interviews (message list accumulation), streaming responses, and model lifecycle. No native tool calling -- prompt-based ReACT replaces it.
- **neo4j >=5.28,<6.0:** Session-per-method async driver pattern already in place. v2 extends GraphStateManager with approximately 8 new methods. Do NOT upgrade to 6.x without a simultaneous Neo4j server upgrade.
- **textual >=8.1.1:** Screen push/pop, Input widget, RichLog, and mode system support all interview and report UI patterns. 8.2.x (latest) is pin-compatible.
- **Jinja2 >=3.1.6 (NEW):** Report template rendering. Handles conditional sections, loops, and markdown output. Zero dependency conflicts with existing stack.
- **aiofiles >=24.1.0 (NEW):** Async file write for report export. Prevents event loop blocking during markdown persistence.
- **Model strategy:** Worker (qwen3.5:9b) for interviews (already loaded post-simulation, fast, no cold-load). Orchestrator (qwen3.5:32b) for report ReACT and dynamic persona generation (both require complex reasoning). Offer interviews BEFORE report to avoid unneeded model swaps.

### Expected Features

**Must have (table stakes for v2.0 milestone):**
- **Live Graph Memory (GRAPH-01, GRAPH-02, GRAPH-03)** -- Every serious simulation framework (Generative Agents, MiroFish, TwinMarket) stores reasoning as it happens. Without it, Neo4j is a write-once dump, not a living memory. All other v2 features depend on this.
- **Post-Simulation Report (REPORT-01, REPORT-02, REPORT-03)** -- A simulation producing 300 decisions across 3 rounds with no summary is a data dump, not an analytical tool. Competitors (MiroFish ReportAgent, TradingAgents chain-of-thought logs) all provide structured post-simulation analysis.
- **Agent Interviews (INT-01, INT-02, INT-03)** -- Stanford Generative Agents (Park et al. 2023) established post-simulation Q&A as the standard evaluation methodology for multi-agent systems. Without interviews, users cannot probe WHY agents made specific decisions.

**Should have (differentiators worth building):**
- **Dynamic Persona Generation (PERSONA-01, PERSONA-02)** -- Entity-aware modifier injection into existing bracket templates. One orchestrator call generates situational context for all 10 brackets. Independent of all other v2 features; can be built in parallel.
- **Richer Agent Interactions (SOCIAL-01, SOCIAL-02)** -- Agents publish public rationale posts that peers read and react to. Key constraint: OASIS-style social features at AlphaSwarm's inference budget require a lightweight approach (zero extra inference calls, posts are part of existing decision output, top-K post selection for peer context injection).
- **Narrative Edges (optional, enhances Report)** -- REFERENCES edges from Decision nodes to Entity nodes. Low complexity, high analytical value for report queries.

**Defer to v2.1+:**
- **Reflection Synthesis** -- Extra orchestrator call between rounds adds ~30s model swap mid-simulation. High complexity, high compute cost, marginal benefit when live graph memory already captures reasoning arcs.
- **Full OASIS social media simulation layer** -- 21 social actions, RecSys engine, follower graphs. Requires 4,000+ LLM calls at cloud scale; incompatible with M1 Max budget.
- **Vector embeddings for agent memory** -- Embedding model adds a third Ollama model violating the 2-model limit. The 300-decision corpus is small enough for exact Cypher queries.
- **Interview-driven persona refinement** -- Development workflow feature; no runtime automation needed in v2.

### Architecture Approach

The v2 architecture extends the existing five-subsystem pipeline (CLI/TUI -> AppState DI container -> SeedInjector -> SimulationEngine -> StateStore/TUI) without restructuring it. Three new modules are added (interview.py, report.py, persona_gen.py) maintaining the flat module convention. GraphStateManager gains approximately 8 new methods covering rationale episode writes, narrative edge writes, and read paths for interviews and reports. The simulation round loop gains two async calls post-dispatch (write_rationale_episodes, write_narrative_edges). Post-simulation features (InterviewEngine, ReportGenerator) are orchestrated outside the simulation lifecycle and must be explicitly serialized to prevent model slot contention.

**Major components:**
1. **PersonaGenerator (persona_gen.py)** -- Extracts seed entities, generates situation-specific bracket modifier text, replaces generic agents within fixed 100-agent grid. Runs between inject_seed() and run_simulation().
2. **GraphStateManager (graph.py, extended)** -- All Cypher operations centralized here. New methods for RationaleEpisode nodes, NARRATIVE edges, READ_POST relationships, and read paths for interview context reconstruction and report tool handlers.
3. **InterviewEngine (interview.py)** -- Stateful chat session per agent. Loads full decision history, rationale history, and influence data from Neo4j at session start. Uses worker LLM with agent's original system prompt restored. Conversation history managed with sliding window to prevent context overflow.
4. **ReportGenerator (report.py)** -- ReACT loop (max 8-10 iterations, hard cap). Tool registry of Cypher query functions. Pydantic-validated JSON action parsing (not regex). Uses orchestrator LLM. Requires model swap from worker. Jinja2 templates produce structured markdown, aiofiles writes async to disk.
5. **StateStore (state.py, extended)** -- Adds interview_active, interview_messages, and report_progress fields. TUI polls at 200ms as before.

### Critical Pitfalls

1. **Model lifecycle collision post-simulation** -- Worker and orchestrator cannot be loaded simultaneously without explicit serialization. Offer interviews (worker model, no swap) before report (orchestrator, 30s swap). Never load orchestrator while simulation-adjacent code expects worker to be available. Add SimulationPhase.INTERVIEWING and SimulationPhase.REPORTING states to gate valid operations.

2. **Write amplification crashing Neo4j** -- Per-agent real-time writes during simulation would increase transaction count from 3 to approximately 2,100 per simulation (700x). Always batch rationale episode writes in a write-behind queue and flush via single UNWIND transaction after each round completes -- exactly as write_decisions() does today. Size connection pool at max_connection_pool_size=32, not the default 100.

3. **ReACT infinite tool-call loops** -- Without a hard iteration cap and duplicate-call detection, the report agent will loop indefinitely on identical queries. Enforce max 8-10 tool calls, cache (tool_name, param_hash) pairs, compress observations to 2-3 sentences before appending to context, and pre-define report sections to constrain exploration.

4. **Social post context window overflow** -- Ten peer rationale posts at full text easily exceeds the 2048 token context limit. When Ollama silently truncates from the front, the system prompt and persona instructions are dropped first, causing all agents to produce generic, undifferentiated responses. Enforce a strict token budget (system: 400, seed: 200, peer decisions: 300, social posts: 300, response headroom: 600) and use a budget-aware context builder.

5. **Prompt injection via dynamic personas** -- Seed rumors are untrusted user input. Extracted entity names flow directly into system prompts; adversarial seeds can override bracket instructions. Sanitize entity names (strip injection patterns, limit to 50 chars), never concatenate raw entity text into system prompts, use template variables only, and validate generated prompts against structural rules.

6. **Hollow interview context** -- v1 schema does not store the peer context agents received when making decisions. Interviews will feel generic without it. Store compressed context summaries (peer IDs, cited post IDs, not full text) on Decision nodes during live graph memory writes. Add a pre-computed "decision narrative" property on Agent nodes summarizing the 3-round arc.

7. **ReACT format conflict between STACK.md and ARCHITECTURE.md** -- STACK.md recommends regex-based text parsing (Simon Willison pattern). ARCHITECTURE.md recommends JSON-structured output with Pydantic validation. Both are valid; the JSON approach is more robust to malformed output. Resolve during Phase 15 implementation with a spike test.

## Implications for Roadmap

Based on combined research, the phase structure is clear and has a single valid ordering driven by data dependencies. All three research files (FEATURES.md, ARCHITECTURE.md, PITFALLS.md) independently arrive at the same build order for the foundational phase. The only ordering divergence is whether Richer Agent Interactions (SOCIAL) comes before or after Interviews -- architecture research recommends SOCIAL second, feature research recommends it fourth. The recommendation below follows the architecture ordering for reasons explained in Phase Ordering Rationale.

### Phase 11: Live Graph Memory

**Rationale:** Foundational dependency. Every other v2 feature reads from the enriched graph data this phase creates. Without RationaleEpisode nodes and NARRATIVE edges, interviews return hollow responses and reports have no rationale data to query. Three independent research files confirm this must come first.
**Delivers:** RationaleEpisode nodes per-agent per-round, NARRATIVE edges across rounds, interview context summaries on Decision nodes, new Neo4j schema indexes. No new modules -- extends graph.py and simulation.py only.
**Addresses:** GRAPH-01 (per-agent episode writes via UNWIND batch), GRAPH-02 (RationaleEpisode with full metadata including cited_agents and timestamps), GRAPH-03 (NARRATIVE edges linking same-agent episodes across rounds, optional REFERENCES edges to Entity nodes).
**Avoids:** Write amplification pitfall (Pitfall 2) -- must use batch UNWIND pattern from day one, not per-agent writes. Connection pool must be explicitly sized at 32.
**Research flag:** Standard patterns. Mirrors existing write_decisions(). No additional research needed.
**Risk:** LOW.

### Phase 12: Richer Agent Interactions

**Rationale:** Architecture research places this second because RationaleEpisode nodes from Phase 11 serve double duty as the social posts that peers read. Building social dynamics into the simulation before post-simulation features means reports and interviews operate on richer, socially-enriched graph data from their first run. Feature research places this fourth but acknowledges independence from live graph memory; the architecture ordering is more efficient.
**Delivers:** Public rationale post field in AgentDecision output, top-K post ranking and injection into peer context for Rounds 2-3, READ_POST edges, optional REACTED_TO edges tracking agreement/disagreement.
**Addresses:** SOCIAL-01 (public_rationale field in decision JSON schema, Post nodes in Neo4j), SOCIAL-02 (top-K post selection ranked by influence weight, injection into _format_peer_context()).
**Avoids:** Context window overflow pitfall (Pitfall 4) -- token-budget-aware context builder must be implemented as the foundation of this phase before any social posts are added to prompts.
**Research flag:** Needs phase research. Social post ranking algorithm (by influence weight vs bracket diversity vs signal divergence) is not specified in research and requires a design decision. The interaction between richer prompts and agent output quality needs empirical validation.
**Risk:** MEDIUM. Modifies the core dispatch path. Careful testing required to confirm richer context improves rather than degrades agent output.

### Phase 13: Dynamic Persona Generation

**Rationale:** Independent of Phases 11-12 in data dependency -- it modifies simulation INPUT (personas), not the simulation loop or output. Placed here rather than in parallel to ensure Phase 11 and 12 graph patterns are stable before a new input source is introduced. Low risk relative to other phases.
**Delivers:** PersonaGenerator module (persona_gen.py), entity-aware bracket modifier generation, persona replacement within fixed 100-agent grid (grid invariant preserved), PersonaGenSettings configuration, option to keep orchestrator loaded between inject_seed() and generate() to avoid a double cold-load.
**Addresses:** PERSONA-01 (orchestrator generates entity-specific bracket modifiers from SeedEvent.entities), PERSONA-02 (modifier injection into generate_personas() pipeline, DynamicPersonaSpec dataclass).
**Avoids:** Prompt injection pitfall (Pitfall 5) -- input sanitization must be the first thing built in this phase, before persona template code. Validate generated prompts against structural rules.
**Research flag:** Standard patterns. Follows existing inject_seed() orchestrator-call pattern. No additional research needed.
**Risk:** LOW.

### Phase 14: Agent Interviews

**Rationale:** Depends on Phase 11 for rationale history context. Post-simulation feature that does not affect core simulation reliability. Benefits from Phase 12 data (richer graph context for interview reconstruction). Feature and architecture research both place this in the second-to-last position.
**Delivers:** InterviewEngine module (interview.py), stateful InterviewSession with graph-backed context, interactive TUI interview mode (push/pop Screen with Input widget and RichLog), CLI interview subcommand, multi-turn conversation with sliding window history management, SimulationPhase.INTERVIEWING state.
**Addresses:** INT-01 (agent context reconstruction -- decisions + rationale history + influence data from Neo4j), INT-02 (conversational loop using worker LLM with agent's original system prompt + decision narrative context), INT-03 (TUI integration accessible from agent grid, clean exit to dashboard).
**Avoids:** Model lifecycle collision (Pitfall 1) -- must use worker model for interviews; never load orchestrator while interview is available. Incomplete interview context (Pitfall 6) -- retrieval query must traverse MADE, CITED, and INFLUENCED_BY relationships, not just Decision nodes. Blocking TUI during inference (anti-pattern) -- run inference as Textual Worker.
**Research flag:** Needs phase research. qwen3.5:9b's interview response quality with 1,250+ token context loads needs empirical validation. Textual Worker pattern for streaming interview responses needs implementation design.
**Risk:** MEDIUM. TUI changes introduce user input handling in a previously output-only interface.

### Phase 15: Post-Simulation Report

**Rationale:** Most complex new component (ReACT loop with tool dispatch). Placed last because it benefits from the richest possible graph data (all prior phases contributing RationaleEpisode, narrative edges, READ_POST edges, social reactions) and because the report query patterns validate that the graph schema is queryable in the ways the report needs. Feature and architecture research both place this last.
**Delivers:** ReportGenerator module (report.py), ReACT loop with hard iteration cap, Pydantic-validated JSON action parsing (ReACTAction model), Cypher query tool registry (consensus, shifts, influence leaders, bracket narratives, convergence), Jinja2 report templates, aiofiles async export to results/, CLI report subcommand, TUI report progress indicator (ReportProgress in StateStore), SimulationPhase.REPORTING state.
**Addresses:** REPORT-01 (ReACT loop using OllamaClient directly, prompt-based tool dispatching -- no LangChain), REPORT-02 (Cypher query tools via GraphStateManager public methods, not raw driver access), REPORT-03 (structured markdown report output, CLI integration, file path displayed in TUI).
**Avoids:** ReACT infinite loops (Pitfall 3) -- hard iteration cap (max 8-10 calls), duplicate tool call detection via (tool_name, param_hash) cache, compressed observations. Model slot competition (Pitfall 7) -- serialize report before or after interview via post-simulation menu, never concurrent. qwen3.5 tool calling bug -- never use `tools=` parameter, always prompt-based.
**Research flag:** Needs phase research. qwen3.5:32b's ability to produce reliable JSON-structured Thought/Tool/Input outputs needs empirical testing before committing to the full tool registry. Run a spike test with 2-3 tools before building all 5-6.
**Risk:** MEDIUM-HIGH. ReACT loop depends on orchestrator output quality. Needs robust 3-tier fallback for malformed JSON actions (same pattern as existing parsing.py).

### Phase Ordering Rationale

- **Phase 11 is non-negotiable first.** All three research files (FEATURES.md, ARCHITECTURE.md, PITFALLS.md) independently confirm this. The data it creates is a prerequisite for every other v2 feature, and Pitfall 6 (hollow interview context) specifically requires context summaries to be written to the graph DURING simulation, not added as an afterthought.
- **Phase 12 before interviews and reports.** Building social dynamics into simulation rounds means the graph that interviews and reports query is richer from the first run. The RationaleEpisode nodes created in Phase 11 serve directly as the social posts in Phase 12, making this a natural continuation rather than a separate track.
- **Phase 13 can shift.** Dynamic persona generation is independent of Phases 12, 14, and 15. It could be built in parallel or earlier without blocking other work. Its placement at Phase 13 (after the simulation loop is stable with enriched writes) reflects conservative risk management.
- **Phase 14 before 15.** Interviews validate that graph read paths (decisions, rationale history, influence data) work correctly for single-agent context reconstruction. These same read patterns underlie report query tools. A working interview is evidence the graph is correctly populated.
- **Never run report and interview concurrently.** Pitfall 7 is explicit: serialize post-simulation activities. The CLI/TUI must present a sequential menu (1. Interview Agents, 2. Generate Report) to prevent model slot competition.

### Research Flags

Phases needing deeper research during planning:
- **Phase 12 (Richer Agent Interactions):** Social post ranking algorithm is unspecified. The interaction between expanded prompts and agent output quality needs empirical design before implementation.
- **Phase 14 (Agent Interviews):** Worker model response quality at interview context token loads needs validation. Textual Worker pattern for streaming responses needs architectural design.
- **Phase 15 (Post-Simulation Report):** ReACT prompt engineering for qwen3.5:32b is the highest-uncertainty element. A 2-3 tool spike test should precede full implementation.

Phases with standard patterns (skip research-phase):
- **Phase 11 (Live Graph Memory):** Pattern mirrors existing write_decisions() exactly. UNWIND batch writes, schema indexes, and GraphStateManager extension are all validated in v1.
- **Phase 13 (Dynamic Persona Generation):** Follows existing inject_seed() orchestrator-call pattern. Risk is low; straightforward extension.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Existing v1 stack fully validated. Two new deps (Jinja2, aiofiles) are mature and conflict-free. qwen3.5 tool calling bug confirmed via two GitHub issues with community reproduction. |
| Features | HIGH | Feature set grounded in primary research papers (Park et al. 2023, OASIS, TwinMarket, TradingAgents) and production frameworks (MiroFish 44.9k stars). Prioritization matrix is internally consistent and grounded in competitor analysis. |
| Architecture | HIGH | Builds on existing codebase patterns with explicit modification points identified per file. Five-phase build structure independently confirmed by both feature and architecture research. Anti-patterns are concrete and specific to existing code (dispatch_wave, session-per-method, UNWIND batch). |
| Pitfalls | HIGH | All 7 critical pitfalls verified against existing codebase architecture. Performance traps are quantified (700x write amplification, 2048 token context limit, 30s cold-load). Recovery strategies provided for each pitfall. |

**Overall confidence:** HIGH

### Gaps to Address

- **ReACT output format:** STACK.md recommends regex-based text parsing (Simon Willison pattern). ARCHITECTURE.md recommends JSON-structured output with Pydantic validation. Both are viable; run a spike test during Phase 15 planning to determine which qwen3.5:32b produces more reliably in the AlphaSwarm ReACT prompt context.
- **Interview context window budget:** The 8K token context estimate for the orchestrator model assumes default Ollama configuration. Verify qwen3.5:32b context window as configured in AlphaSwarm's Modelfile.orchestrator. If pinned to 4K, the sliding window triggers after approximately 10 exchanges instead of 22.
- **Social post ranking algorithm:** SOCIAL-02 requires top-K post selection for peer context injection. Ranking criteria (by influence weight, bracket diversity, or signal divergence) are unspecified in all research files. Design decision required during Phase 12 planning.
- **ARCHITECTURE.md and FEATURES.md phase ordering disagreement:** Features research recommends SOCIAL last (Phase 14, after Interviews); Architecture research recommends SOCIAL second (Phase 12, before Interviews). This summary recommends architecture order. Validate this choice during Phase 12 planning by confirming that social enrichment materially improves interview context quality.

## Sources

### Primary (HIGH confidence)
- [Generative Agents: Interactive Simulacra of Human Behavior (Park et al. 2023)](https://arxiv.org/abs/2304.03442) -- Interview evaluation methodology, memory stream architecture
- [OASIS: Open Agent Social Interaction Simulations (CAMEL-AI)](https://github.com/camel-ai/oasis) -- Social action patterns, RecSys-driven propagation
- [TwinMarket: Scalable Behavioral and Social Simulation](https://arxiv.org/html/2502.01506v2) -- Forum-style social posts, hot-score ranking, opinion leader emergence
- [MiroFish (GitHub, 44.9k stars)](https://github.com/666ghj/MiroFish) -- ReACT report agent, agent interviews, OASIS social integration
- [TradingAgents: Multi-Agent LLM Financial Trading](https://github.com/TauricResearch/TradingAgents) -- Chain-of-thought logs, hierarchical report writing
- [Ollama tool calling bug #14493](https://github.com/ollama/ollama/issues/14493) -- Confirmed broken qwen3.5 tool calling
- [Ollama tool calling bug #14745](https://github.com/ollama/ollama/issues/14745) -- 9b variant prints tool calls as text
- [Neo4j Python driver concurrency docs](https://neo4j.com/docs/python-manual/current/concurrency/) -- AsyncSession constraints and performance recommendations
- [ReACT: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) -- Original ReACT paper
- [Jinja2 PyPI (v3.1.6)](https://pypi.org/project/Jinja2/) -- Template engine, Python >=3.7
- [aiofiles PyPI](https://pypi.org/project/aiofiles/) -- Async file I/O for asyncio
- [Textual PyPI (v8.2.1)](https://pypi.org/project/textual/) -- Screen modes, Input, RichLog
- [Neo4j Text2Cypher ReACT agent example](https://github.com/neo4j-field/text2cypher-react-agent-example) -- ReACT + Neo4j integration pattern

### Secondary (MEDIUM confidence)
- [Graphiti: Knowledge Graph Memory (Neo4j/Zep)](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) -- Bi-temporal episode model patterns
- [Neo4j Agent Memory (neo4j-labs)](https://github.com/neo4j-labs/agent-memory) -- Episodic/semantic memory schema patterns
- [Simon Willison ReACT pattern](https://til.simonwillison.net/llms/python-react-pattern) -- Minimal Python ReACT implementation
- [Population-Aligned Persona Generation (2025)](https://arxiv.org/abs/2509.10127) -- Three-stage persona generation pipeline
- [PersonaAgent: LLM Agents Meet Personalization (2025)](https://arxiv.org/abs/2506.06254) -- Test-time persona alignment
- [OWASP LLM Top 10 2025: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) -- Indirect prompt injection via untrusted data
- [Memory in LLM-based Multi-agent Systems (TechRxiv)](https://www.techrxiv.org/doi/full/10.36227/techrxiv.176539617.79044553/v1) -- Context degradation and memory synchronization challenges
- [Ollama Keep-Alive Memory Management](https://markaicode.com/ollama-keep-alive-memory-management/) -- Model eviction behavior and cold-load latency

---
*Research completed: 2026-03-31*
*Ready for roadmap: yes*
