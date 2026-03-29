# AlphaSwarm

Multi-agent financial simulation engine. Ingest a seed rumor, run a 3-round consensus cascade across 100 AI personas, and visualize real-time state in a terminal dashboard.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Ollama](https://ollama.com/) (local inference)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for Neo4j)

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Create Ollama models

```bash
ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator
ollama create alphaswarm-worker -f modelfiles/Modelfile.worker
```

### 3. Start Neo4j

First time only:

```bash
docker run -d --name neo4j --restart unless-stopped \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/alphaswarm \
  neo4j:community
```

After restarts, Neo4j starts automatically with Docker Desktop (thanks to `--restart unless-stopped`).

### 4. Run

```bash
uv run start
```

Enter a market rumor when prompted (e.g. "Apple is acquiring OpenAI for $300B") and watch the simulation.

## Dashboard

The TUI dashboard shows:

- **Header** -- current phase (Seeding, Round 1/2/3, Complete) and elapsed time
- **Agent Grid** -- 10x10 grid of 100 agents, color-coded: green (BUY), red (SELL), gray (HOLD)
- **Rationale Sidebar** -- scrolling feed of agent reasoning
- **Telemetry** -- RAM %, tokens/sec, queue depth, inference slots
- **Brackets** -- sentiment bars for 10 agent archetypes (Quants, Degens, Whales, etc.)

Press `q` to quit.

## Architecture

- **Runtime:** async Python with `asyncio`
- **Inference:** Ollama (`qwen3.5:35b` orchestrator, `qwen3.5:9b` workers)
- **State:** Neo4j graph database
- **UI:** Textual terminal dashboard
- **Config:** Pydantic settings (see `.env.example`)

## Hardware Target

Apple M1 Max 64GB. Memory-aware throttling pauses inference at 90% RAM utilization.
