# Feature Landscape

**Domain:** Multi-agent LLM-powered financial market simulation engine (local-first, consensus cascade)
**Researched:** 2026-03-24
**Comparable Systems:** TradingAgents, StockSim, TwinMarket, MiroFish-Offline, FCLAgent, AlphaAgents, OASIS, CrewAI finance agents

---

## Table Stakes

Features users expect from any credible multi-agent financial simulation. Missing any of these and the system feels like a toy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Heterogeneous agent personas** | Every framework (TradingAgents, TwinMarket, StockSim, MiroFish) uses distinct agent archetypes with unique risk profiles and behavioral logic. Homogeneous agents produce boring, unrealistic consensus. | Medium | AlphaSwarm already plans 10 bracket archetypes (Quants, Degens, Sovereigns, etc.). This is correct. Personas must include: risk tolerance, information bias, decision heuristic, and influence weight. |
| **Multi-round iterative reasoning** | TradingAgents uses structured debate (bullish vs bearish researchers). TwinMarket runs multi-step BDI (Belief-Desire-Intention) loops. FCLAgent iterates trading decisions across time steps. Single-shot LLM calls produce shallow, undifferentiated outputs. | Medium | AlphaSwarm's 3-round cascade (Initial Reaction, Peer Influence, Final Consensus) is well-aligned with the field. The peer influence round is the differentiating middle step most systems skip. |
| **Seed/scenario injection** | Every simulation needs a trigger event. MiroFish ingests documents to build knowledge graphs. TwinMarket injects market news. TradingAgents starts from a stock ticker + time window. Without a clear input mechanism, the system has no purpose. | Low | AlphaSwarm's "Seed Rumor" concept is solid. Must include entity extraction (who/what is affected) to ground agent reasoning. |
| **Agent decision logging and rationale capture** | TradingAgents logs full chain-of-thought per agent. StockSim exports research data. AlphaAgents uses structured debate transcripts. Without logging, the simulation is a black box with no analytical value. | Low | Every agent response must be persisted with: agent ID, round number, input context, raw LLM output, parsed sentiment/action, and timestamp. Neo4j is well-suited for this. |
| **Sentiment/position output per agent** | All surveyed systems produce per-agent outputs (buy/sell/hold, bullish/bearish, sentiment score). This is the atomic unit of simulation value. Without it, there is no data to analyze. | Low | Must be structured and machine-readable, not just free text. A normalized sentiment score (-1.0 to 1.0) plus a categorical action (BULLISH/BEARISH/NEUTRAL) plus free-text rationale. |
| **Async/concurrent agent execution** | StockSim uses RabbitMQ for async coordination. ScaleSim addresses GPU memory for concurrent LLM serving. TradingAgents runs analyst teams concurrently. Sequential 100-agent execution would take hours. | High | AlphaSwarm's asyncio + dynamic semaphore approach is mandatory. Ollama's 16-parallel limit means batching in waves of 16. The ResourceGovernor (psutil-driven) is table stakes for local hardware. |
| **Resource/memory management** | ScaleSim specifically addresses memory management for large-scale multi-agent LLM simulations. MiroFish-Offline documents hardware requirements (16-32GB RAM). Running 100 agents on 64GB without memory governance will OOM. | High | The dynamic semaphore + psutil monitoring at 90% threshold is exactly what the field demands. Must include: concurrency throttling, model-swap awareness (cold-load penalty for 70B is ~30s), and graceful degradation. |
| **Configurable agent count and types** | Every framework allows adjusting population size and composition. Fixed-count simulations limit experimentation. | Low | AlphaSwarm should parameterize the 100-agent / 10-bracket split. Allow running 20-agent quick simulations for testing and 200-agent deep runs when hardware allows. |
| **Structured output parsing** | TradingAgents, StockSim, and AlphaAgents all use structured output formats for agent decisions. Raw LLM text is unreliable for downstream aggregation. | Medium | Use JSON-mode or schema-constrained output from Ollama. Define a strict response schema: `{sentiment: float, action: str, confidence: float, rationale: str, cited_agents: list[str]}`. |

## Differentiators

Features that would set AlphaSwarm apart. Not universally expected, but high-value when present.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Dynamic influence topology (graph-based)** | TwinMarket uses social network dynamics but with a simulated social media platform as the mechanism. TradingAgents has a fixed role hierarchy. AlphaSwarm's approach -- where INFLUENCED_BY edges form dynamically from citation/agreement patterns -- is novel and more realistic than static hierarchies. This is the single strongest differentiator. | High | Neo4j is the right choice here. Edges should carry: weight (agreement strength), cycle_id (round scoping), and direction. The topology should be queryable mid-simulation for analysis. No other surveyed system builds influence graphs from emergent agent behavior in real-time. |
| **Real-time TUI dashboard with agent grid** | StockSim has interactive HTML charts. MiroFish-Offline has a Vue.js frontend. TradingAgents has no visualization. Most systems are batch-oriented with post-hoc analysis. A live 10x10 grid showing agent states updating in real-time during simulation is visually compelling and operationally useful for debugging. | High | The snapshot-based 200ms tick rendering is the right approach. Show: agent color-coded by sentiment, selected agent rationale in sidebar, hardware telemetry in footer. This is a differentiator because most competing systems have zero real-time visualization. |
| **Consensus cascade with peer influence** | TradingAgents has debate between bullish/bearish researchers but it is role-based, not population-based. TwinMarket has social influence but through a simulated social media platform. AlphaSwarm's Round 2 (Peer Influence) where agents read neighbors' Round 1 outputs and adjust is a distinct mechanism. The cascade produces measurably different final consensus than single-round systems. | Medium | The peer influence round must inject actual neighbor opinions into the agent's prompt context. Use Neo4j to query cycle-scoped neighbor sentiments. This is where the graph topology pays off. |
| **Simulation replay and time-travel** | Audit trail frameworks (FINOS Agent Decision Audit) emphasize the ability to replay agent decisions. Most simulation frameworks run forward-only. The ability to re-examine Round 2 decisions with different neighbor inputs enables counterfactual analysis. | Medium | Neo4j's cycle-scoped edges make this feasible. Store full state snapshots per round. Replay does not need to re-run LLM inference -- just re-render stored decisions with the stored topology. |
| **Bracket-level aggregate analytics** | No surveyed system groups agents into meaningful archetypes and then reports archetype-level consensus. TradingAgents has roles but not population brackets. Showing "Quants are 80% bearish while Degens are 90% bullish" tells a story that per-agent data cannot. | Low | Aggregate sentiment by bracket after each round. Display in TUI as bracket summary bars or heatmap. Low implementation cost, high analytical value. |
| **Entity extraction from seed rumor** | MiroFish builds knowledge graphs from seed documents. Most other systems take structured inputs (ticker symbols, time windows). Extracting entities (companies, people, sectors, geopolitical factors) from a free-text rumor and injecting them into agent prompts is more flexible and narrative-driven. | Medium | Use llama4:70b orchestrator for NER on the seed rumor. Extract: affected entities, sector, sentiment polarity of the rumor itself, and potential second-order effects. Feed extracted entities into agent prompts so agents reason about specific things, not vague text. |
| **Miro network visualization (Phase 2)** | No surveyed system exports to an external collaboration/visualization tool. Miro board showing agent nodes, influence edges, and sentiment coloring would be uniquely shareable and presentable. | Medium | Correctly deferred to Phase 2. The Miro API v2 batcher with 2-second buffering is the right approach. Bulk-create nodes, then bulk-create edges. Export final-round topology only to minimize API calls. |
| **Prompt injection for scenario variants** | Beyond seed rumor injection, the ability to inject mid-simulation shocks ("Fed announces emergency rate hike during Round 2") would enable stress testing. No surveyed system supports mid-simulation event injection. | Low | Add an optional Round 2 "shock event" parameter that gets prepended to all agent prompts in that round. Simple to implement, high analytical value. |
| **Exportable simulation reports** | MiroFish-Offline generates structured reports via a ReportAgent. StockSim exports research data. Post-simulation human-readable reports summarizing the consensus cascade, key disagreements, and bracket-level outcomes add polish and utility. | Medium | Generate a markdown or HTML report after simulation completes. Include: seed rumor, entity extraction results, per-round bracket summaries, final consensus, notable outlier agents, and the influence topology summary. |

## Anti-Features

Features to explicitly NOT build. These are traps that look valuable but add complexity without matching AlphaSwarm's core value proposition.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Real market data integration** | StockSim and TradingAgents integrate live/historical market data feeds. AlphaSwarm is a *rumor simulation engine*, not a trading system. Adding real data feeds creates a massive integration burden, data licensing issues, and shifts the product away from its core value (simulating narrative-driven reactions). | Keep the system purely narrative-driven. The seed rumor IS the data. If users want to ground rumors in reality, they can write factually accurate rumors. |
| **Actual trade execution or portfolio management** | TradingAgents and CrewAI finance agents support actual trade execution. AlphaSwarm simulates *reactions*, not *transactions*. There is no order book, no portfolio, no P&L. Adding these would triple the scope. | Output is sentiment and consensus, not trades. If a user wants to act on the simulation output, that is their decision outside the system. |
| **Backtesting against historical data** | StockSim's dual-mode backtesting is a major feature. But AlphaSwarm simulates forward reactions to novel rumors, not historical replay. Backtesting requires historical data (which is out of scope) and a fundamentally different architecture. | The "replay" feature covers re-examining past simulations. That is sufficient. Forward simulation only. |
| **Fine-tuned or custom-trained LLMs** | Some research systems fine-tune models for financial tasks. AlphaSwarm uses off-the-shelf Ollama models. Fine-tuning adds weeks of work, requires training data, and couples the system to specific model versions. | Use prompt engineering and structured output parsing. The bracket archetype personas are defined in prompts, not model weights. This is more flexible and maintainable. |
| **Multi-user / collaborative mode** | OASIS scales to 1M agents with distributed infrastructure. AlphaSwarm is local-first, single-operator. Adding multi-user support would require networking, auth, state synchronization -- none of which serve the core use case. | Single operator, single machine. The TUI is for one person watching a simulation unfold. |
| **GPU inference or cloud LLM APIs** | TradingAgents supports OpenAI, Anthropic, etc. AlphaSwarm is deliberately local-only via Ollama on M1 Max. Adding cloud APIs creates cost, latency variability, and dependency on external services. | Ollama-only. CPU/Metal inference. The ResourceGovernor is designed for local memory constraints. |
| **Complex order book / market microstructure** | StockSim and FCLAgent implement limit order books, slippage, latency modeling. AlphaSwarm agents express sentiment, not orders. There is no matching engine. | Agents output sentiment + rationale. The consensus cascade IS the "market mechanism." No order book needed. |
| **Reinforcement learning or adaptive agents** | Some ABM systems use RL for agent adaptation. LLM agents with prompt-based personas are sufficient for AlphaSwarm's 3-round horizon. RL adds training loops, reward function design, and convergence concerns. | Agents are stateless across simulations (but stateful within a simulation's 3 rounds via Neo4j). Persona consistency comes from prompts, not learned behavior. |

## Feature Dependencies

```
Seed Rumor Injection
  --> Entity Extraction (entities ground agent prompts)
    --> Agent Persona Prompts (entities + bracket archetype = contextualized reasoning)
      --> Round 1: Initial Reaction (each agent responds independently)
        --> Neo4j Persistence (store Round 1 outputs + agent metadata)
          --> Round 2: Peer Influence (query neighbor sentiments from Neo4j)
            --> Dynamic Influence Topology (INFLUENCED_BY edges form from citations)
              --> Round 3: Final Consensus Lock (agents read updated topology)
                --> Bracket-Level Aggregation (compute per-archetype consensus)
                  --> TUI Dashboard (render grid, sidebar, telemetry)
                  --> Simulation Report (export results)
                  --> Miro Visualization [Phase 2] (export topology to Miro board)

Resource Governor (parallel dependency -- must exist before any LLM calls)
  --> Async Batch Inference (waves of 16 via Ollama)
    --> All three cascade rounds depend on this

Structured Output Parsing (parallel dependency -- needed for all agent outputs)
  --> Sentiment aggregation, topology formation, TUI rendering all consume parsed output
```

## MVP Recommendation

**Prioritize (Phase 1 -- Core Engine):**

1. **Seed Rumor Injection + Entity Extraction** -- the simulation starts here. Without it, nothing else matters.
2. **Heterogeneous Agent Personas** -- 10 bracket archetypes with distinct risk profiles. This is the atomic unit of simulation diversity.
3. **3-Round Consensus Cascade** -- Initial Reaction, Peer Influence, Final Consensus Lock. This is the core product.
4. **Async Concurrent Execution + ResourceGovernor** -- without this, 100 agents on M1 Max is not viable.
5. **Neo4j Persistence** -- cycle-scoped sentiment storage enables Round 2 peer reads and post-simulation analysis.
6. **Structured Output Parsing** -- reliable JSON output from agents is load-bearing for everything downstream.
7. **Agent Decision Logging** -- every agent response persisted with full context. Non-negotiable for a simulation engine.
8. **Dynamic Influence Topology** -- INFLUENCED_BY edges forming from citation patterns. This is the primary differentiator and should be in v1.

**Prioritize (Phase 1 -- Interface):**

9. **TUI Dashboard** -- 10x10 agent grid, rationale sidebar, hardware telemetry footer. The visual is what makes the simulation tangible.
10. **Bracket-Level Aggregation** -- low-cost, high-value analytics layer on top of per-agent data.

**Defer to Phase 2:**

- **Miro Visualization** -- API-constrained, requires batcher. Core engine must be solid first. (Correctly identified in PROJECT.md)
- **Simulation Replay** -- valuable but not blocking. Store the data in Phase 1; build the replay UI in Phase 2.
- **Exportable Reports** -- nice-to-have polish. The TUI is the Phase 1 interface.
- **Mid-Simulation Shock Injection** -- interesting but adds complexity to the cascade flow. Phase 2 enhancement.
- **Configurable Agent Count** -- hardcode 100 agents / 10 brackets for Phase 1. Parameterize later.

**Never Build:**

- Real market data feeds, trade execution, backtesting, fine-tuned models, multi-user mode, GPU/cloud inference, order book microstructure, or RL-based adaptive agents.

## Sources

- [TradingAgents - GitHub](https://github.com/TauricResearch/TradingAgents) -- Multi-agent LLM trading framework with debate mechanism (HIGH confidence)
- [StockSim - GitHub](https://github.com/harrypapa2002/StockSim) -- Dual-mode LLM financial market simulator (HIGH confidence)
- [TwinMarket - arXiv](https://arxiv.org/abs/2502.01506) -- Scalable behavioral/social financial simulation, ICLR 2025 (HIGH confidence)
- [MiroFish-Offline - GitHub](https://github.com/nikmcfly/MiroFish-Offline) -- Offline multi-agent simulation with Neo4j + Ollama (HIGH confidence)
- [OASIS - GitHub](https://github.com/camel-ai/oasis) -- Open Agent Social Interaction Simulations, 1M agents (MEDIUM confidence -- social media focused, not directly financial)
- [AlphaAgents - arXiv](https://arxiv.org/abs/2508.11152) -- BlackRock multi-agent LLM portfolio construction (HIGH confidence)
- [FCLAgent - arXiv](https://arxiv.org/abs/2510.12189) -- Fundamental-Chartist-LLM agent for market simulation (HIGH confidence)
- [ScaleSim - arXiv](https://arxiv.org/html/2601.21473) -- Memory management for large-scale multi-agent LLM serving (MEDIUM confidence)
- [CrewAI Finance Agents](https://medium.com/@sid23/ai-powered-stock-trading-agents-using-crewai-8acc605b9dfa) -- CrewAI trading agent examples (MEDIUM confidence -- blog posts, not primary source)
- [FINOS Agent Decision Audit](https://air-governance-framework.finos.org/mitigations/mi-21_agent-decision-audit-and-explainability.html) -- Audit and explainability standards for agent decisions (HIGH confidence)
- [Emergent Mind - Multi-Agent LLM Financial Trading](https://www.emergentmind.com/topics/multi-agent-llm-financial-trading) -- Topic overview and paper aggregation (MEDIUM confidence)
