# AlphaSwarm: Master Project Specification

## 1. System Objective
Build a localized, multi-agent financial simulation engine based on OASIS/Mirofish principles. The system will ingest a single "Seed Rumor" and simulate the cascading market reactions across 100 distinct AI personas, visualizing the consensus formation in real-time.

## 2. The Swarm Mechanics
The swarm consists of 100 participant agents, divided into 10 brackets with varying risk profiles and influence weights:
1.  **Quants (10):** Algorithmic, sentiment-driven, fast reaction.
2.  **Degens (20):** High leverage, trend-chasing, highly volatile.
3.  **Sovereigns (10):** Macro-political focus, massive capital, slow reaction.
4.  **Macro (10):** Geopolitical focus, energy/supply chain bias.
5.  **Suits (10):** Institutional, risk-averse, fundamentals-driven.
6.  **Insiders (10):** Industry-specific knowledge, capex focus.
7.  **Agents (15):** Autonomous trading bots, zero emotion.
8.  **Doom-Posters (5):** Perma-bears, short-sellers, contrarian.
9.  **Policy Wonks (5):** Regulatory focus, legal bias.
10. **Whales (5):** Deep value, private credit, illiquid asset focus.

## 3. Simulation Loop (The Engine)
- **Phase 1: Seed Injection:** The orchestrator (Llama 4) parses a market rumor and extracts key entities.
- **Phase 2: Swarm Processing (Batched):** Agents process the rumor in parallel batches of 16. They query Neo4j for past context, then output a decision (Buy, Sell, Hold) and a rationale.
- **Phase 3: Interaction & Consensus:** Agents read the outputs of highly influential peers and update their own sentiment.

## 4. UI/UX: Mission Control (Textual)
The terminal interface must feature a clean, minimalist aesthetic with high data density:
- **Header:** Global Status (Idle, Running, Syncing) and live Global TPS (Tokens Per Second).
- **Main Body:** A 10x10 dynamic grid representing the 100 agents. Nodes change color/state based on current activity (Thinking, Resolved, Error).
- **Sidebar:** A streaming log of the most impactful "Agent Rationale" outputs.
- **Footer:** Local hardware telemetry (VRAM usage, API Queue size).

## 5. Visual Visualization (Miro)
- Implement a spatial layout algorithm.
- Map Agent sentiment to node color (e.g., Green = Bullish, Red = Bearish).
- Draw dynamic connectors between agents when one cites or reacts to another's rationale, clustering consensus groups visually.

## 6. Future Enhancements (v2)

Adapted from deep research into [MiroFish](https://github.com/666ghj/MiroFish) and [OASIS](https://github.com/camel-ai/oasis) — all features designed for local-first execution (no cloud APIs).

### Agent Interviews
After simulation completes, select any agent from the grid and have a live conversation. The worker model stays loaded post-simulation. Interview context includes the agent's full persona, all 3 rounds of decisions, peer influences received, and rationale history.

### Live Graph Memory
Feed agent actions back into Neo4j in real time during simulation — rationale episodes, signal flip events, influence interactions. Creates a living memory graph that evolves throughout the cascade and enables post-simulation graph exploration.

### Post-Simulation Report Generation
A ReACT-style agent queries the Neo4j graph after the simulation ends and produces a structured markdown report: consensus summary, key dissenting voices, bracket-level trends, signal flip analysis, and confidence distributions.

### Richer Agent Interactions
Evolve beyond BUY/SELL/HOLD signals. Agents publish short rationale posts that other agents read and react to — creating organic social influence dynamics. Influence weights shift based on rationale engagement rather than just signal alignment.

### Dynamic Persona Generation
Extract entities and context from the seed rumor to generate situation-specific personas. A rumor about oil markets spins up energy traders, OPEC analysts, and pipeline engineers alongside the standard 10 brackets.
