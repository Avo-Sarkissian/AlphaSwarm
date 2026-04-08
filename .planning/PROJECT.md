# AlphaSwarm

## What This Is

A localized, multi-agent financial simulation engine that ingests a single "Seed Rumor" and simulates cascading market reactions across 100 distinct AI personas. The system extracts stock tickers from seed rumors, fetches live market data (price history, financials, earnings, news), enriches agent prompts with bracket-tailored market context, and runs a 3-round iterative consensus cascade on local hardware (M1 Max 64GB). Results are visualized via a Textual TUI dashboard (including per-ticker consensus panel) and persisted in Neo4j. Post-simulation capabilities include agent interviews and a ReACT-driven market analysis report comparing agent consensus with actual market indicators.

## Core Value

The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — grounded in real market data, the simulation engine is the product.

## Requirements

### Validated

**v1.0 Core Engine:**
- ✓ Async batched Ollama inference with adaptive ResourceGovernor (psutil-driven semaphore) — v1.0
- ✓ Exponential backoff for Ollama retries — v1.0
- ✓ Memory pressure monitoring with automatic concurrency throttling at 90% utilization — v1.0
- ✓ Neo4j GraphRAG for cycle-scoped sentiment storage and peer decision reads — v1.0
- ✓ Seed rumor injection with entity extraction via orchestrator LLM — v1.0
- ✓ 100-agent swarm across 10 bracket archetypes with distinct risk profiles — v1.0
- ✓ Round 1 standalone pipeline (seed → dispatch → persist) with CLI run command — v1.0
- ✓ 3-round iterative cascade (Initial Reaction → Peer Influence → Final Consensus Lock) — v1.0
- ✓ Dynamic influence topology — INFLUENCED_BY edges form from citation/agreement patterns — v1.0
- ✓ Textual TUI: 10x10 agent grid with HSL color-coded cells and HeaderBar — v1.0
- ✓ Snapshot-based TUI rendering (200ms tick, diff-only cell updates, non-blocking Textual Worker) — v1.0
- ✓ TUI panels: RationaleSidebar, TelemetryFooter (RAM/TPS/Queue/Slots), BracketPanel — v1.0
- ✓ Miro API v2 batcher stubbed with 2s buffer and bulk payload interface — v1.0

**v2.0 Engine Depth:**
- ✓ Live graph memory — RationaleEpisode nodes with REFERENCES edges to Entity nodes — v2.0
- ✓ Richer agent interactions — agents publish rationale posts that peers read/react to — v2.0
- ✓ Dynamic persona generation — entity-aware bracket modifiers from SeedEvent — v2.0
- ✓ Agent interviews — post-simulation Q&A with any agent in-character — v2.0
- ✓ Post-simulation report — ReACT agent queries Neo4j, outputs structured markdown — v2.0

**v3.0 Stock-Specific Recommendations with Live Data:**
- ✓ Orchestrator LLM ticker co-extraction alongside entity extraction in a single call — v3.0
- ✓ SEC company_tickers.json validation — invalid symbols rejected before simulation — v3.0
- ✓ Top-3 ticker cap with dropped-ticker display in CLI injection summary — v3.0
- ✓ Async yfinance market data pipeline (price history, financials, earnings) with asyncio.to_thread() + per-ticker locks — v3.0
- ✓ Alpha Vantage fallback + graceful degradation with visible CLI warnings — v3.0
- ✓ AV NEWS_SENTIMENT headlines field in MarketDataSnapshot — v3.0
- ✓ 1-hour disk cache with atomic temp-file-rename; cache hits logged at INFO — v3.0
- ✓ Budget-capped bracket-tailored market context injected into all 100 agent prompts pre-Round 1 — v3.0
- ✓ Bracket-specific market data slices (Quant/Technical, Macro/Insider, Default) — v3.0
- ✓ Graceful parse fallback for new ticker fields — backward-compatible None defaults — v3.0
- ✓ TickerDecision structured output (ticker, direction, expected_return_pct, time_horizon) — v3.0
- ✓ Lenient TickerDecision parsing — malformed entries dropped without PARSE_ERROR — v3.0
- ✓ Per-ticker TickerConsensusPanel in TUI — confidence-weighted voting + bracket bars — v3.0
- ✓ Dual-signal display (weighted + majority vote) per ticker — v3.0
- ✓ Bracket disagreement breakdown per ticker in TUI — v3.0
- ✓ Market context report section comparing agent consensus with live market indicators — v3.0

### Active

- [ ] Miro API v2 live network visualization — spatial layout, dynamic connectors (VIS-01, VIS-02)
- [ ] Simulation replay from stored Neo4j state (REPLAY-01)
- [ ] Exportable simulation reports — HTML export (REPLAY-02)
- [ ] Mid-simulation shock injection (REPLAY-03)
- [ ] RAG vector retrieval layer for agent context (deferred from v3.0; v3.1 candidate)

### Out of Scope

- Trade execution — no real money, no broker integration
- Historical backtesting — forward simulation only
- Fine-tuned LLMs — base Ollama models with prompt engineering
- Multi-user / network mode — single-operator local-first design
- GPU / cloud inference — M1 Max Metal only, no CUDA or cloud APIs
- Order book microstructure — sentiment simulation, not tick-level market mechanics
- RL-based adaptive agents — agents use LLM inference, not reinforcement learning

## Context

- **Hardware:** Apple M1 Max, 64GB unified memory — all inference runs locally via Ollama
- **LLM Strategy:** `llama4:70b` for orchestration (seed parsing, consensus aggregation), `qwen3.5:7b` for 100 worker agents
- **Ollama Constraints:** `OLLAMA_NUM_PARALLEL=16` baseline, but dynamically governed. `OLLAMA_MAX_LOADED_MODELS=2`
- **Agent Brackets:** Quants (10), Degens (20), Sovereigns (10), Macro (10), Suits (10), Insiders (10), Agents (15), Doom-Posters (5), Policy Wonks (5), Whales (5)
- **Orchestration:** Ruflo v3.5 hierarchical swarm logic
- **Current State (v3.0):** ~10,075 LOC Python source (src/), ~4,120 LOC tests. 23 phases shipped across 3 milestones. Full v3 data pipeline operational: ticker extraction → market data fetch → agent enrichment → consensus aggregation → TUI display → report generation.
- **Market Data:** yfinance primary, Alpha Vantage fallback (25 calls/day free tier), 1-hour disk cache, Neo4j Ticker nodes with summary stats. Headlines via AV NEWS_SENTIMENT.
- **Known Limitations:** Token budget char estimates vs actual qwen3.5 tokenizer counts unvalidated; num_ctx=4096 KV cache memory impact unprofiled.

## Constraints

- **Hardware**: M1 Max 64GB — all inference local, no cloud APIs. Memory pressure is the primary bottleneck.
- **Ollama**: Max 2 models loaded simultaneously, 16 parallel baseline (dynamically adjusted). Cold-loading a 70B model takes ~30s.
- **Miro API**: 2-second minimum buffer between POST/PATCH. Bulk operations only. 429 handling mandatory.
- **Concurrency**: All LLM calls and API interactions must be async (asyncio). No blocking I/O on the main event loop.
- **Python**: 3.11+ required. Strong typing throughout.
- **Market Data APIs**: Alpha Vantage free tier 25 calls/day — disk caching mandatory. yfinance not thread-safe — asyncio.to_thread() + per-ticker locks required.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Dynamic asyncio.Semaphore over hardcoded parallelism | VRAM ceiling unknown during peak context loads; psutil monitoring at 90% threshold | ✓ Rewritten in Phase 03 — TokenPool (Queue-based) with 5-state governor machine, dual-signal monitoring (psutil + sysctl) |
| Snapshot-based TUI rendering (200ms tick) | 100 async agents would freeze Textual if pushing per-agent updates; decouples agent throughput from render throughput | ✓ Implemented in Phase 09 — StateStore.snapshot() + set_interval, diff-based AgentCell updates only |
| Cycle-scoped Neo4j edges (cycle_id on relationships) | Enables fast current-cycle reads without full history scans; composite index keeps queries under 5ms | ✓ Implemented in Phase 04 — composite index on (cycle_id, round), UNWIND batch writes, session-per-method isolation |
| Dynamic influence topology | Edges form from citation/agreement patterns, not static bracket hierarchies; more realistic consensus formation | ✓ Implemented in Phase 08 — INFLUENCED_BY edges from citation patterns |
| 3-round iterative cascade | Round 1: Initial reaction, Round 2: Peer influence, Round 3: Final consensus lock. Balances depth with compute cost | ✓ Implemented in Phases 06-07 |
| Miro deferred post-v1 | Most API-constrained component; core engine and TUI must be solid first. Batcher stubbed but not blocking | ⚠ Still deferred — Active in roadmap |
| Pre-simulation market data enrichment | All market data must complete before Round 1 begins — agents need consistent context | ✓ Phase 17-18 — fetch_market_data() called in simulation startup, before first dispatch |
| yfinance in asyncio.to_thread() with per-ticker locks | yfinance is not thread-safe; concurrent access causes data corruption | ✓ Phase 17 — _ticker_locks dict, TaskGroup for parallel fetching |
| Bracket-specific market data slices | Different archetypes need different information — Quants want technicals, Macro wants earnings | ✓ Phase 18 — 3-slice format_market_block; Macro in Earnings/Insider slice |
| Dual-signal TUI display (weighted + majority) | Both aggregation methods surface different insights; weighted more accurate, majority more intuitive | ✓ Phase 19 — `w:BUY 0.74 | m:SELL (54%) R3` display |
| RAG deferred to v3.1 | Ship core data pipeline first; prove market data grounding stable before adding vector retrieval | — Pending — Active requirement |
| Ticker validator as optional callback kwarg | CDN may be unreachable; simulation should proceed without validation rather than crash | ✓ Phase 21 — None-safe pass-through; simulation degrades gracefully |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-08 after v3.0 milestone — Stock-Specific Recommendations with Live Data*
