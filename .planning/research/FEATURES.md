# Feature Research: v2.0 Engine Depth

**Domain:** Multi-agent LLM-powered financial market simulation engine (local-first, consensus cascade)
**Researched:** 2026-03-31
**Confidence:** HIGH
**Scope:** v2.0 milestone features ONLY. v1 features (10 phases) are validated and shipped.

## Existing v1 Foundation (Already Built)

These are validated and will not be re-researched. Listed here to establish dependency roots for v2 features.

- 100-agent swarm across 10 bracket archetypes with distinct risk profiles
- 3-round iterative cascade (Initial Reaction, Peer Influence, Final Consensus Lock)
- Dynamic influence topology via INFLUENCED_BY edges from citation/agreement patterns
- Textual TUI: 10x10 agent grid, rationale sidebar, telemetry footer, bracket panel
- Neo4j graph state with cycle-scoped indexes and batch writing
- Seed rumor injection with entity extraction via orchestrator LLM
- ResourceGovernor with TokenPool and 5-state governor machine
- StateStore bridge (simulation writes, TUI reads snapshots at 200ms tick)

---

## Feature Landscape

### Table Stakes (Users Expect These for v2)

Features that a "deeper simulation engine" milestone MUST deliver. Without these, v2 feels like polish, not substance.

| Feature | Why Expected | Complexity | Dependencies on Existing | Notes |
|---------|--------------|------------|--------------------------|-------|
| **Live graph memory (rationale episodes)** | v1 writes decisions in batch after each round completes. Every serious simulation engine (Generative Agents, MiroFish, TwinMarket) stores agent reasoning as it happens, not post-hoc. Real-time persistence enables mid-simulation queries, crash recovery, and progressive graph analysis. Without this, Neo4j is a write-once dump, not a living memory. | MEDIUM | Extends `GraphStateManager.write_decisions()` and `StateStore` writes. Requires new Episode/Rationale node types in Neo4j schema. Must not block agent inference hot path. | Graphiti (Zep AI) pioneered bi-temporal episode ingestion in Neo4j -- events track both "when it happened" and "when it was recorded." AlphaSwarm's simpler need: write Decision nodes immediately per-agent instead of batch-per-round, plus add RationaleEpisode nodes linking Agent -> Round -> Rationale with timestamps. |
| **Post-simulation report** | Every competing framework (MiroFish ReportAgent, TradingAgents chain-of-thought logs, StockSim export) provides structured post-simulation analysis. A simulation that produces 300 decisions across 3 rounds but no summary is a data dump, not an analytical tool. Users need a synthesized narrative. | MEDIUM | Reads from Neo4j (all Decision, Agent, Cycle, Entity nodes). Uses orchestrator LLM. Leverages existing `compute_bracket_summaries()` logic. | ReACT pattern (Thought-Action-Observation loop) is the right approach: the report agent thinks about what to analyze, queries Neo4j via Cypher tools, observes results, iterates. Output is structured markdown. Does NOT require LangChain/LangGraph -- implement a minimal ReACT loop with Ollama directly. |
| **Agent interviews (post-sim Q&A)** | Stanford Generative Agents (Park et al. 2023) established agent interviews as the standard evaluation methodology. Their 100-evaluator study proved that interviews across 5 categories (self-knowledge, memory, planning, reactions, reflection) are how you validate simulation believability. MiroFish Step 5 implements this. Without interviews, users cannot probe WHY agents made specific decisions. | MEDIUM | Requires full persona context + all 3 rounds of that agent's decisions from Neo4j. Uses worker LLM (not orchestrator) with the agent's original system prompt restored. | The key insight from Generative Agents: interviews must reconstruct the agent's full memory context -- persona, all decisions across rounds, peer context received, entities reacted to. The agent answers "in character" using its original system prompt plus retrieved decision history as injected context. |

### Differentiators (Competitive Advantage)

Features that set AlphaSwarm apart from MiroFish, TwinMarket, and OASIS. Not required for a complete v2, but valuable.

| Feature | Value Proposition | Complexity | Dependencies on Existing | Notes |
|---------|-------------------|------------|--------------------------|-------|
| **Richer agent interactions (social posts/reactions)** | OASIS implements 21 social actions (post, like, comment, repost, follow). TwinMarket uses forum-style post/upvote/repost with hot-score ranking. AlphaSwarm v1's peer influence is implicit (agents see peer decisions, not explicit social content). Making rationale visible as "posts" that peers explicitly react to creates emergent social dynamics -- opinion leader emergence, information cascades, behavioral polarization via homophily. | HIGH | Extends Round 2-3 peer influence pipeline. Requires new Post/Reaction node types in Neo4j. Modifies `_dispatch_round()` and `_format_peer_context()` to include social post content. Increases prompt token count per agent. | CRITICAL CONSTRAINT: OASIS achieves rich interactions at cloud scale (4,000+ inference calls). AlphaSwarm's 300-call budget on M1 Max means social interactions must be lightweight. The approach: agents produce a "public rationale post" as part of their decision output (zero extra inference calls), peers consume top-K ranked posts (ranked by influence weight) as additional context. Reactions are implicit -- agreement/citation patterns already captured by existing CITED edges. Do NOT build a full social media platform layer. |
| **Dynamic persona generation (entity-aware)** | MiroFish chains ontology_generator + oasis_profile_generator to create situation-specific personas from seed text. Recent research (Population-Aligned Persona Generation, 2025) shows that personas grounded in the specific scenario produce more diverse, realistic responses than generic archetypes. AlphaSwarm v1 uses static bracket templates with round-robin modifiers -- effective but not adaptive to the seed rumor's content. | MEDIUM | Consumes `SeedEvent.entities` from seed injection pipeline. Extends `generate_personas()` in config.py. Uses orchestrator LLM to generate entity-aware modifier text per bracket. Must preserve the 10-bracket structure (100 agents, same counts). | The design: after entity extraction, the orchestrator generates 1-2 sentences of entity-specific context per bracket (e.g., for a "Tesla recalls vehicles" rumor, Quants get "Tesla's P/E ratio is 45x with 2.3M vehicles delivered last quarter", Degens get "TSLA options chain shows 40% IV crush potential"). These modifier sentences are injected into the existing system_prompt_template. The bracket archetype stays fixed; only the situational modifier changes. One orchestrator call generates all 10 bracket modifiers in a single JSON response. |
| **Narrative edge formation** | MiroFish builds narrative connections between agent actions and knowledge graph entities during simulation. AlphaSwarm v1 has INFLUENCED_BY edges (citation-based) but no edges connecting decisions to the specific entities they reference. Adding REFERENCES edges from Decision nodes to Entity nodes would enable queries like "Which agents were most influenced by the Tesla entity?" and "Did Quants focus on Tesla while Macro focused on the EV sector?" | LOW | Extends `write_decisions()` to create REFERENCES edges. Requires entity mention detection in rationale text (simple keyword matching against extracted entities, not a second LLM call). | Low complexity because it piggybacks on existing entity extraction and decision writing. High analytical value for the post-simulation report agent. |
| **Reflection synthesis** | Generative Agents triggers reflections when accumulated importance scores exceed a threshold, producing higher-level insights stored as tree-structured memories. AlphaSwarm could synthesize per-bracket "reflections" after Round 2 -- bracket-level consensus patterns like "Quants converged on SELL after seeing Sovereigns' bearish positioning" -- and inject these as additional context in Round 3. | HIGH | Would add an extra orchestrator LLM call between Round 2 and Round 3. Extends prompt context for Round 3 agents. New Reflection node type in Neo4j. | Marked HIGH complexity because it adds an orchestrator inference step mid-simulation (model swap overhead ~30s) and increases Round 3 prompt tokens. Powerful but expensive on M1 Max. Defer unless live graph memory + report + interviews ship cleanly. |
| **Interview-driven agent profile refinement** | PersonaAgent (2025) demonstrates test-time persona alignment: after receiving feedback, the agent iteratively rewrites its persona prompt. For AlphaSwarm, interviews could surface persona weaknesses (e.g., a Quant agent giving emotional responses) and feed corrections back into the system prompt template. | LOW | Depends on Agent Interviews being built first. Modifies `BRACKET_MODIFIERS` in config.py based on interview findings. | This is a development workflow feature, not a runtime feature. After running a simulation and interviewing agents, the developer manually refines prompts. No automation needed initially. |

### Anti-Features (Commonly Requested, Explicitly Not Building)

Features that seem like natural v2 additions but create problems. These traps are more dangerous now because v1 is working and the temptation to over-scope is real.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Full OASIS social media simulation layer** | OASIS has 21 actions, recommendation systems, follower graphs, trending algorithms. Looks like the "right" way to do social interactions. | OASIS requires 4,000+ LLM calls per simulation at cloud scale. The RecSys engine alone is complex. Adding follow/unfollow/mute/trending to 100 local agents on M1 Max would 10x inference costs and 5x codebase complexity with marginal simulation quality improvement. | Lightweight social posts: agents include a "public rationale" in their decision output. Peers see top-K ranked posts. Implicit reactions via existing CITED edges. Zero extra inference calls. |
| **Zep Cloud or external memory service** | Zep/Graphiti achieves 300ms P95 retrieval with hybrid semantic+keyword+graph search. Seems like the best memory layer. | Violates local-first constraint. SaaS dependency. AlphaSwarm's 100-agent, 3-round structure is simple enough that Neo4j direct queries (already under 5ms with composite indexes) outperform any memory abstraction layer. | Direct Neo4j Cypher queries. The existing schema with cycle-scoped indexes is already performant. Add Episode nodes for live memory, not an external service. |
| **LangChain/LangGraph dependency for ReACT report agent** | LangGraph's `create_react_agent` is the standard way to build ReACT agents. Community support, battle-tested. | Adds a heavyweight dependency graph (LangChain core + LangGraph + LangSmith tracing). AlphaSwarm's Ollama client is already built. The ReACT loop is 40 lines of code: prompt -> parse thought/action -> execute tool -> inject observation -> repeat. | Minimal hand-rolled ReACT loop using existing `OllamaClient.chat()`. Define 3-4 Cypher query tools as Python functions. No framework dependency. |
| **Vector embeddings for agent memory retrieval** | Generative Agents uses embedding-based relevance scoring for memory retrieval. Seems necessary for "real" agent memory. | Requires an embedding model loaded alongside the worker/orchestrator models. Ollama's 2-model limit means either: (a) swap models constantly (30s cold-load penalty each time), or (b) use a separate embedding service (violates local-first simplicity). For 100 agents with 3 rounds, the total memory corpus is ~300 entries -- small enough for exact Cypher queries. | Direct Cypher traversal queries filtered by cycle_id, agent_id, and round. No embeddings needed for a 300-decision corpus. |
| **Autonomous agent-to-agent conversations** | Generative Agents has agents talk to each other naturally. OASIS has comments and group chats. Seems like the next step for "richer interactions." | Each conversation is 2+ additional LLM calls per agent pair. With 100 agents and even 5% interaction rate, that is 250 extra calls. On M1 Max with ~2-3 tok/s per agent, this adds 30+ minutes per round. The consensus cascade already captures inter-agent influence through peer context injection. | Peer context injection (already built) IS the conversation mechanism. Agents "hear" each other through formatted peer decisions. Making this a "post" format adds narrative richness without the compute cost of actual back-and-forth dialogue. |
| **Real-time streaming report generation** | Generating the report while the simulation runs, updating as each round completes. | The report agent needs the FULL simulation context (all 3 rounds, all entities, all influence edges) to generate a coherent analysis. Partial reports after Round 1 would be misleading. The orchestrator model also cannot be loaded during worker model inference (2-model limit). | Post-simulation batch report. Run after Round 3 completes and worker model is unloaded. Load orchestrator, run ReACT loop against Neo4j, generate markdown, unload orchestrator. |

## Feature Dependencies

```
[Live Graph Memory] (GRAPH-01, GRAPH-02, GRAPH-03)
    |
    |-- extends --> [Neo4j write_decisions] (existing)
    |-- enables --> [Post-Simulation Report] (report queries live graph data)
    |-- enables --> [Agent Interviews] (interviews query decision history)
    |
    v
[Post-Simulation Report] (REPORT-01, REPORT-02, REPORT-03)
    |
    |-- requires --> [Live Graph Memory] (must read rationale episodes)
    |-- requires --> [Entity nodes in Neo4j] (existing from seed injection)
    |-- uses --> [Orchestrator LLM] (ReACT loop via ollama-python)
    |
    v
[Agent Interviews] (INT-01, INT-02, INT-03)
    |
    |-- requires --> [Live Graph Memory] (reconstruct decision history)
    |-- requires --> [Agent Personas] (existing system prompts)
    |-- uses --> [Worker LLM] (agent responds in character)
    |
    v
[Richer Agent Interactions] (SOCIAL-01, SOCIAL-02)
    |
    |-- requires --> [Live Graph Memory] (posts stored as episodes)
    |-- extends --> [_dispatch_round / _format_peer_context] (existing)
    |-- extends --> [Neo4j schema] (Post nodes, REACTED_TO edges)
    |
    v
[Dynamic Persona Generation] (PERSONA-01, PERSONA-02)
    |
    |-- requires --> [SeedEvent.entities] (existing from seed injection)
    |-- extends --> [generate_personas() in config.py] (existing)
    |-- uses --> [Orchestrator LLM] (generate entity-aware modifiers)
    |-- independent of --> [Live Graph Memory, Report, Interviews]

[Narrative Edges] (optional, enhances Report)
    |
    |-- requires --> [Entity nodes] (existing)
    |-- extends --> [write_decisions] (add REFERENCES edges)
    |-- enhances --> [Post-Simulation Report] (richer entity-level queries)
```

### Dependency Notes

- **Live Graph Memory must come first:** Both the Report agent and Interview system depend on being able to query per-agent, per-round rationale episodes from Neo4j. Without live graph memory, these features would need to reconstruct context from the in-memory `SimulationResult` object, which is fragile and unavailable after the simulation process exits.
- **Dynamic Persona Generation is independent:** It only depends on the existing seed injection pipeline and can be built in parallel with any other v2 feature. It modifies the simulation INPUT (personas), not the simulation PROCESS or OUTPUT.
- **Richer Interactions depends on Live Graph Memory:** Social posts need to be stored as graph episodes so they can be recommended to peers and later queried by the report agent.
- **Report before Interviews:** The report agent validates that the Neo4j query tools work correctly against the enriched graph. The same query patterns are reused for interview context reconstruction.
- **Narrative Edges enhance Report but are optional:** The report agent can function without entity-level REFERENCES edges by doing text-match against rationale strings. REFERENCES edges make the queries faster and more precise.

## Phase Recommendation (v2 Milestone)

### Phase 11: Live Graph Memory (GRAPH-01, GRAPH-02, GRAPH-03) -- Build First

Foundation for all other v2 features. Enriches Neo4j from a batch write-dump into a living simulation memory.

- [ ] GRAPH-01: Per-agent real-time decision writing (move from batch to immediate writes)
- [ ] GRAPH-02: RationaleEpisode nodes with timestamps, round context, peer context received
- [ ] GRAPH-03: Narrative REFERENCES edges from Decision nodes to Entity nodes

**Why first:** Everything else reads from the enriched graph. Without this, Report and Interviews must reconstruct context from in-memory objects.

### Phase 12: Post-Simulation Report (REPORT-01, REPORT-02, REPORT-03) -- Build Second

Validates the Neo4j query tools that Interviews will also use. Produces the first tangible v2 output.

- [ ] REPORT-01: Minimal ReACT loop (Thought-Action-Observation) using OllamaClient
- [ ] REPORT-02: Cypher query tools (bracket summaries, influence topology, entity analysis, shift metrics)
- [ ] REPORT-03: Structured markdown report output with CLI integration

**Why second:** The ReACT loop and Cypher tools are reusable. Building them for the report agent first validates the pattern before applying it to interviews.

### Phase 13: Agent Interviews (INT-01, INT-02, INT-03) -- Build Third

Interactive post-simulation Q&A with any agent. Reuses query tools from Report phase.

- [ ] INT-01: Agent context reconstruction (persona + decisions + peer context from Neo4j)
- [ ] INT-02: Conversational interview loop using worker LLM with agent's system prompt
- [ ] INT-03: TUI integration (interview mode accessible from agent grid)

**Why third:** Reuses GRAPH query patterns and worker LLM infrastructure. The interview is essentially "load this agent's full context and let the user chat with it."

### Phase 14: Richer Agent Interactions (SOCIAL-01, SOCIAL-02) -- Build Fourth

Adds social dynamics to the consensus cascade. Most complex v2 feature.

- [ ] SOCIAL-01: "Public rationale post" field in AgentDecision output + Post nodes in Neo4j
- [ ] SOCIAL-02: Top-K post ranking and injection into peer context for Rounds 2-3

**Why fourth:** This modifies the core simulation loop. All foundational features (live graph, report, interviews) should be stable before changing the cascade pipeline.

### Phase 15: Dynamic Persona Generation (PERSONA-01, PERSONA-02) -- Build Fifth (or parallel)

Entity-aware persona enrichment. Independent of other v2 features.

- [ ] PERSONA-01: Orchestrator generates entity-specific bracket modifiers from SeedEvent
- [ ] PERSONA-02: Modifier injection into generate_personas() pipeline

**Why fifth/parallel:** Independent dependency chain. Can be built at any time after Phase 11 starts. Placed last because it modifies simulation INPUT quality, not simulation PROCESS depth.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Risk | Priority |
|---------|------------|---------------------|------|----------|
| Live Graph Memory | HIGH | MEDIUM | LOW | P1 |
| Post-Simulation Report | HIGH | MEDIUM | MEDIUM | P1 |
| Agent Interviews | HIGH | MEDIUM | LOW | P1 |
| Dynamic Persona Generation | MEDIUM | LOW-MEDIUM | LOW | P2 |
| Richer Agent Interactions | MEDIUM | HIGH | HIGH | P2 |
| Narrative Edges | MEDIUM | LOW | LOW | P2 |
| Reflection Synthesis | LOW | HIGH | HIGH | P3 |
| Interview-Driven Refinement | LOW | LOW | LOW | P3 |

**Priority key:**
- P1: Must have for v2.0 milestone. These ARE the milestone.
- P2: Should have. Add if P1 features ship cleanly without schedule pressure.
- P3: Nice to have. Future consideration or organic development-time improvements.

## Competitor Feature Analysis (v2 Context)

| Feature | MiroFish | OASIS | TwinMarket | Generative Agents | AlphaSwarm v2 |
|---------|----------|-------|------------|-------------------|---------------|
| **Agent Interviews** | Step 5: post-sim Q&A with full memory context | Not supported | Not supported | 5-category interview evaluation with 100 human evaluators | Reconstruct agent context from Neo4j + chat with worker LLM in character |
| **Live Graph Memory** | Zep Cloud + Neo4j real-time updates via zep_graph_memory_updater | SQLite batch dumps | In-memory state only | Memory stream with recency/importance/relevance scoring | Direct Neo4j episode writes per-agent, per-round. No external service. |
| **Post-Sim Report** | ReACT report_agent.py with tool-use | Post-hoc matplotlib scripts | No report feature | No automated report | Minimal ReACT loop with Cypher tools, markdown output |
| **Social Interactions** | OASIS social media substrate (posts, likes, comments) | 21 social actions, RecSys, follower graphs | Forum posts + hot-score ranking + reposts | Natural conversation between agents | Lightweight: public rationale posts + top-K ranking. Zero extra inference calls. |
| **Dynamic Personas** | ontology_generator + oasis_profile_generator pipeline | LLM-generated user profiles | Basic trader archetypes | Two-hour interview-based agent creation | Entity-aware modifier injection into existing bracket templates. Single orchestrator call. |
| **Influence Graph** | Static knowledge graph, no dynamic influence | Follower graph (explicit, not emergent) | Social network with homophily | No influence tracking | INFLUENCED_BY edges from citation patterns + REFERENCES to entities. Dynamic and emergent. |

**Key insight:** AlphaSwarm's advantage is the combination of dynamic influence topology + live TUI + local-first constraints. No competitor has all three. MiroFish has the richest feature set but depends on cloud services (Zep, OpenAI). OASIS has the deepest social simulation but requires massive compute. AlphaSwarm's niche is deep simulation quality at local scale.

## Sources

- [Generative Agents: Interactive Simulacra of Human Behavior (Park et al. 2023)](https://arxiv.org/abs/2304.03442) -- Interview evaluation methodology, memory stream with recency/importance/relevance retrieval, reflection synthesis. The foundational paper for agent interviews. (HIGH confidence)
- [OASIS: Open Agent Social Interaction Simulations (CAMEL-AI)](https://github.com/camel-ai/oasis) -- 21 social actions, RecSys-driven information propagation, hot-score post ranking. Source for social interaction patterns. (HIGH confidence)
- [TwinMarket: Scalable Behavioral and Social Simulation for Financial Markets](https://arxiv.org/html/2502.01506v2) -- Forum-style social posts, hot-score ranking, information propagation chains, opinion leader emergence. Source for lightweight social dynamics. (HIGH confidence)
- [Graphiti: Knowledge Graph Memory for an Agentic World (Neo4j/Zep)](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) -- Bi-temporal episode model, incremental entity resolution, Neo4j-backed knowledge graph memory. Source for live graph memory patterns. (MEDIUM confidence -- blog post, architecture validated via GitHub repo)
- [Neo4j Agent Memory (neo4j-labs)](https://github.com/neo4j-labs/agent-memory) -- Episodic/semantic/procedural memory patterns in Neo4j. Graph schema recommendations for agent memory. (HIGH confidence)
- [Modeling Agent Memory in Neo4j (Alex Gilmore, Neo4j Dev Blog)](https://medium.com/neo4j/modeling-agent-memory-d3b6bc3bb9c4) -- Episodic memory as question-answer pairs, semantic memory as entity-relationship graphs, temporal memory with versioned nodes. (HIGH confidence)
- [ReAct Agent Pattern (LangChain Tutorials)](https://langchain-tutorials.github.io/langchain-react-agent-pattern-2026/) -- Thought-Action-Observation loop implementation, tool definition patterns. (MEDIUM confidence)
- [Population-Aligned Persona Generation (2025)](https://arxiv.org/abs/2509.10127) -- Three-stage pipeline for generating personas from real-world data. Source for dynamic persona generation patterns. (MEDIUM confidence -- preprint)
- [PersonaAgent: LLM Agents Meet Personalization (2025)](https://arxiv.org/abs/2506.06254) -- Test-time persona alignment, episodic+semantic memory for persona context. Source for entity-aware persona enrichment. (MEDIUM confidence -- preprint)
- [MiroFish (GitHub, 44.9k stars)](https://github.com/666ghj/MiroFish) -- ReACT report agent, post-sim agent interviews, OASIS social integration, Zep graph memory. Primary source for v2 feature inspiration. (HIGH confidence, deep-researched 2026-03-28)
- [TradingAgents: Multi-Agent LLM Financial Trading](https://github.com/TauricResearch/TradingAgents) -- Structured debate, chain-of-thought logging, hierarchical report writing. (HIGH confidence)
- [Generative Agent Simulations of 1,000 People (Stanford, 2024)](https://arxiv.org/pdf/2411.10109) -- Two-hour interview-based agent creation, 85% response replication accuracy. (HIGH confidence)

---
*Feature research for: AlphaSwarm v2.0 Engine Depth*
*Researched: 2026-03-31*
