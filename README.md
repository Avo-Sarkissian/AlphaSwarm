# AlphaSwarm

> A localized, multi-agent financial simulation engine — built to run entirely on-device.

Feed it a market rumor. Watch 100 AI personas — quants, degens, whales, policy wonks, and more — debate, revise, and converge across 3 rounds of iterative consensus. All inference runs locally via Ollama. No cloud. No latency. No leaks.

---

## How It Works

1. **Seed** — You enter a natural-language market rumor (e.g. *"Iran and U.S. reach a peace deal"*)
2. **Round 1** — 100 agents independently form an initial signal: BUY, SELL, or HOLD
3. **Round 2** — Agents see peer decisions and revise based on influence weights
4. **Round 3** — Final convergence pass; measures signal flips and consensus strength
5. **Visualize** — Everything streams live to a terminal dashboard as it happens

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

## Prerequisites

| Tool | Purpose |
|---|---|
| Python 3.11+ | Runtime |
| [uv](https://docs.astral.sh/uv/) | Package manager |
| [Ollama](https://ollama.com/) | Local LLM inference |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs Neo4j graph database |

**Hardware target:** Apple M1 Max 64GB. Memory-aware throttling kicks in at 90% RAM — the simulation auto-slows before it crashes.

---

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Build the Ollama models

AlphaSwarm uses two custom model variants — an orchestrator (35B) for parsing rumors, and a worker (9B) for agent inference.

```bash
ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator
ollama create alphaswarm-worker -f modelfiles/Modelfile.worker
```

> This pulls ~30GB total on first run. Make sure Ollama is running first.

### 3. Start Neo4j (first time only)

```bash
docker run -d --name neo4j --restart unless-stopped \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/alphaswarm \
  neo4j:community
```

The `--restart unless-stopped` flag means Neo4j will automatically start whenever Docker Desktop opens — no manual step needed on future reboots.

### 4. Launch

```bash
uv run start
```

Or add a shell alias so you can just type `start` from anywhere:

```bash
echo 'alias start="cd ~/Documents/VS\ Code/AlphaSwarm && uv run start"' >> ~/.zshrc
source ~/.zshrc
```

---

## Dashboard

The terminal UI updates in real time as agents form decisions:

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

| Area | What it shows |
|---|---|
| Header | Phase, round counter, elapsed time |
| Agent Grid | 10x10 cells — green (BUY), red (SELL), gray (HOLD) |
| Rationale Sidebar | Scrolling feed of agent reasoning snippets |
| Telemetry | RAM %, tokens/sec, queue depth, available inference slots |
| Brackets | Sentiment distribution bars per archetype |

Press `q` to quit.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.11+, `asyncio` (100% non-blocking) |
| Inference | Ollama — `qwen3.5:35b` (orchestrator), `qwen3.5:9b` (workers) |
| Graph State | Neo4j Community via async driver |
| Terminal UI | Textual |
| Validation | Pydantic + pydantic-settings |
| Logging | structlog (structured JSON) |
| Package Manager | uv |

---

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

Key settings:

```env
ALPHASWARM_GOVERNOR__BASELINE_PARALLEL=8     # concurrent agent slots
ALPHASWARM_GOVERNOR__MEMORY_THROTTLE_PERCENT=80.0  # start throttling at 80%
ALPHASWARM_GOVERNOR__MEMORY_PAUSE_PERCENT=90.0     # pause queue at 90%
```

---

## Roadmap

Planned features — all local-first, no cloud dependencies.

### Agent Interviews

After the simulation completes, select any agent from the grid and have a live conversation. Ask a Whale why they went contrarian, or grill a Degen about their FOMO. The worker model stays loaded post-simulation to power interactive Q&A with full persona and decision context.

### Live Graph Memory

Currently Neo4j captures a snapshot of each round's decisions. This upgrade feeds agent actions back into the graph in real time — rationale text, signal flips, influence events — creating a living memory that evolves throughout the cascade. Enables richer peer context in later rounds and post-simulation graph exploration.

### Post-Simulation Report Generation

A ReACT-style agent that queries the Neo4j graph after the simulation ends and produces a structured market analysis report: consensus summary, key dissenting voices, bracket-level trends, signal flip analysis, and confidence distributions. Output as markdown, viewable in the TUI or exported.

### Richer Agent Interactions

Evolve beyond simple BUY/SELL/HOLD signals. Agents publish short rationale posts that other agents read and react to — creating organic social influence dynamics rather than pure vote-counting. Inspired by [OASIS](https://github.com/camel-ai/oasis) social simulation research.

### Dynamic Persona Generation

Instead of static archetypes, extract entities and context from the seed rumor itself to generate situation-specific personas. A rumor about oil markets would spin up energy traders, OPEC analysts, and pipeline engineers alongside the standard brackets.
