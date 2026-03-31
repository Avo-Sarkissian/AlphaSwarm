# AlphaSwarm

**Multi-agent financial simulation engine that runs 100 AI personas through a 3-round consensus cascade — entirely on local hardware.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ollama](https://img.shields.io/badge/inference-Ollama-orange.svg)](https://ollama.com/)
[![Neo4j](https://img.shields.io/badge/graph-Neo4j-brightgreen.svg)](https://neo4j.com/)
[![Textual](https://img.shields.io/badge/TUI-Textual-purple.svg)](https://textual.textualize.io/)

Feed it a market rumor. Watch 100 AI agents — quants, degens, whales, policy wonks, and more — independently analyze it, observe each other's positions, and iteratively converge toward consensus. All inference runs locally via Ollama. No cloud. No API keys. No data leaves your machine.

---

## Key Features

- **100 autonomous agents** across 10 distinct market archetypes, each with unique risk profiles, biases, and decision heuristics
- **3-round iterative consensus** — independent analysis, peer influence, final convergence — with measurable opinion shifts between rounds
- **Dynamic influence topology** — agent-to-agent influence edges form organically from citation and agreement patterns (Neo4j graph), not static hierarchies
- **Real-time terminal dashboard** — live 10x10 agent grid, streaming rationale feed, bracket sentiment bars, and hardware telemetry
- **Memory-aware resource governance** — dynamic concurrency control via `psutil` monitoring, auto-throttles at 80% RAM, pauses at 90%
- **100% local** — dual-model Ollama pipeline (35B orchestrator + 9B workers), Neo4j in Docker, zero cloud dependencies

---

## How It Works

```
Seed Rumor ──► Orchestrator (35B) ──► Entity Extraction
                                          │
                    ┌─────────────────────┘
                    ▼
              Round 1: 100 agents form independent signals (BUY / SELL / HOLD)
                    │
                    ▼
              Round 2: Agents read top-5 peer decisions, revise positions
                    │
                    ▼
              Round 3: Final convergence — consensus lock, influence edges solidify
                    │
                    ▼
              Results: Per-agent decisions, bracket summaries, influence graph
```

---

## Dashboard

The Textual TUI updates in real time as agents form decisions:

```
AlphaSwarm  |  Round 2/3  |  ● Round 2  |  00:04:12
┌─────────────────────────────┐  ┌─────────────────────────┐
│  ■ ■ ■ ■ ■ ■ ■ ■ ■ ■      │  │ Rationale               │
│  ■ ■ ■ ■ ■ ■ ■ ■ ■ ■      │  │ > Q-07 [BUY] peace...   │
│  ■ ■ ■ ■ ■ ■ ■ ■ ■ ■      │  │ > D-14 [SELL] risk...   │
│  ... 10x10 agent grid ...  │  │ > W-02 [BUY] long-t...  │
└─────────────────────────────┘  └─────────────────────────┘
RAM: 72%  |  TPS: 48.3  |  Queue: 12  |  Slots: 8
Quants      [████████░░]  80%   Brackets
Degens      [████░░░░░░]  40%   ...
```

| Panel | Description |
|---|---|
| **Header** | Simulation phase, round counter, elapsed time |
| **Agent Grid** | 10x10 cells color-coded by signal — green (BUY), red (SELL), gray (HOLD) |
| **Rationale** | Scrolling feed of agent reasoning, prioritized by influence weight |
| **Telemetry** | Live RAM %, tokens/sec, inference queue depth, governor slot count |
| **Brackets** | Per-archetype sentiment distribution updated after each round |

**Controls:** `q` quit | `s` save results to markdown

---

## Agent Archetypes

| Bracket | Count | Personality |
|---|---|---|
| Quants | 10 | Data-driven, skeptical of narratives |
| Degens | 20 | High-risk, FOMO-driven speculators |
| Sovereigns | 10 | Ultra-conservative, geopolitically aware |
| Macro | 10 | Think in regimes, rates, and cycles |
| Suits | 10 | Institutional, consensus-following |
| Insiders | 10 | Read between the regulatory lines |
| Agents | 15 | Algorithmic, rule-based, no emotion |
| Doom-Posters | 5 | Perma-bears, amplify negative narratives |
| Policy Wonks | 5 | Believe policy is the ultimate market mover |
| Whales | 5 | Contrarian, decade-horizon bets |

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    AlphaSwarm                         │
│                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │  Ollama   │   │  Simulation  │   │   Textual    │ │
│  │  35B/9B   │◄─►│   Engine     │──►│   TUI        │ │
│  │  Models   │   │  (asyncio)   │   │  Dashboard   │ │
│  └──────────┘   └──────┬───────┘   └──────────────┘ │
│                        │                             │
│                        ▼                             │
│               ┌──────────────┐                       │
│               │    Neo4j     │                       │
│               │  Graph DB    │                       │
│               │  (Docker)    │                       │
│               └──────────────┘                       │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │          Resource Governor                    │    │
│  │  psutil monitoring · dynamic semaphore ·      │    │
│  │  auto-throttle at 80% · pause at 90%          │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ with strict typing |
| Concurrency | `asyncio` — 100% non-blocking, `TaskGroup`-based dispatch |
| Inference | Ollama — `qwen3.5:35b` orchestrator, `qwen3.5:9b` workers |
| Graph State | Neo4j Community — cycle-scoped edges, UNWIND batch writes, async driver |
| Terminal UI | Textual — snapshot-based rendering at 200ms intervals |
| Validation | Pydantic + pydantic-settings |
| Logging | structlog (structured JSON with per-agent correlation IDs) |
| Package Manager | uv |

---

## Quick Start

### Prerequisites

| Tool | Purpose |
|---|---|
| [Python 3.11+](https://www.python.org/downloads/) | Runtime |
| [uv](https://docs.astral.sh/uv/) | Package manager |
| [Ollama](https://ollama.com/) | Local LLM inference |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs Neo4j |

**Hardware target:** Apple Silicon with 64GB unified memory. The resource governor dynamically adjusts concurrency for available RAM.

### 1. Install

```bash
git clone https://github.com/Avo-Sarkissian/AlphaSwarm.git
cd AlphaSwarm
uv sync
```

### 2. Build models

```bash
ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator
ollama create alphaswarm-worker -f modelfiles/Modelfile.worker
```

### 3. Start Neo4j (first time only)

```bash
docker run -d --name neo4j --restart unless-stopped \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/alphaswarm \
  neo4j:community
```

### 4. Run

```bash
uv run start
```

---

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

Key settings:

```env
ALPHASWARM_GOVERNOR__BASELINE_PARALLEL=8          # starting concurrent agent slots
ALPHASWARM_GOVERNOR__MAX_PARALLEL=16              # max slots under low memory pressure
ALPHASWARM_GOVERNOR__MEMORY_THROTTLE_PERCENT=80.0 # begin throttling
ALPHASWARM_GOVERNOR__MEMORY_PAUSE_PERCENT=90.0    # pause inference queue
```

---

## Roadmap

Planned features — all local-first, no cloud dependencies.

| Feature | Description |
|---|---|
| **Agent Interviews** | Post-simulation live Q&A with any agent — full persona and decision context |
| **Live Graph Memory** | Real-time Neo4j updates during simulation — rationale episodes, signal flips, influence events as queryable edges |
| **Report Generation** | ReACT agent queries Neo4j post-simulation and generates a structured market analysis report |
| **Social Influence** | Agents publish rationale posts that peers read and react to — organic influence dynamics beyond vote-counting |
| **Dynamic Personas** | Extract entities from the seed rumor to spawn domain-specific agents alongside standard brackets |
| **Web Dashboard** | Vue 3 + D3.js browser UI — live agent grid, force-directed influence graph, rationale feed, bracket charts ([MiroFish](https://github.com/666ghj/MiroFish)-inspired) |

---

## License

MIT
