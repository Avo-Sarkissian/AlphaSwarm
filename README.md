# AlphaSwarm

**Multi-agent financial simulation engine that runs 100 AI personas through a multi-round consensus cascade (3 rounds by default). Local-first: inference runs on your own hardware, with optional cloud providers.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ollama](https://img.shields.io/badge/inference-Ollama-orange.svg)](https://ollama.com/)
[![Neo4j](https://img.shields.io/badge/graph-Neo4j-brightgreen.svg)](https://neo4j.com/)
[![React](https://img.shields.io/badge/frontend-React%20%2B%20TS-61dafb.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![D3.js](https://img.shields.io/badge/viz-D3.js-f7931e.svg)](https://d3js.org/)

Feed it a market rumor. Watch 100 AI agents (institutions, sell-side analysts, quants, degens, short sellers, and more) independently analyze it, observe each other's positions, and iteratively converge toward consensus. Inference runs locally through Ollama by default; OpenAI-compatible and Anthropic providers are strictly opt-in (see [Cloud inference](#cloud-inference-optional)).

---

## Screenshots

Screenshots of a real run will be added here. The images that used to be here
were captures of the design prototype's mock data, not of the shipped app, so
they were removed.

---

## Key Features

- **100 autonomous agents** across 10 market archetypes (v2 composition), each with its own biases and decision heuristics
- **3-round iterative consensus** with independent analysis, peer influence, and final convergence producing measurable opinion shifts between rounds
- **Dynamic influence topology** where agent-to-agent influence edges form organically from citation and agreement patterns via Neo4j graph
- **React + FastAPI web dashboard** with D3 visualization, live WebSocket at 5Hz, 100-agent influence graph (deterministic layout), bracket panels, rationale feed, replay mode, and advisory panel
- **Live graph memory** where Neo4j persists every decision, rationale episode, signal flip, and INFLUENCED_BY edge as queryable state
- **Post-simulation capabilities** including click-to-interview any agent (multi-turn Q&A), replay past cycles from Neo4j state without re-inference, and ReACT-agent-generated market analysis reports
- **Dynamic persona generation** where the orchestrator extracts entities from the seed rumor to inject situation-specific bracket modifiers
- **Shock injection** to inject disruptive news or events mid-simulation between rounds, prompting agents to re-evaluate with fresh context
- **Memory-aware resource governance** with dynamic concurrency control via `psutil` and macOS memory-pressure monitoring, auto-throttle at 80% RAM, and pause at 90%
- **Local-first** with a dual-model Ollama pipeline on MLX (27B dense orchestrator + 35B-A3B MoE worker), Neo4j in Docker, and optional OpenAI-compatible or Anthropic providers

---

## How It Works

```
Seed Rumor --> Orchestrator (27B) --> Entity Extraction + Dynamic Persona Modifiers
                                          |
                    +---------------------+
                    v
              Round 1: 100 agents form independent signals (BUY / SELL / HOLD)
                    |
                    v  (optional Shock Injection)
                    v
              Round 2: Agents read selected peer rationales, revise positions
                    |
                    v  (optional Shock Injection)
                    v
              Round 3: Final convergence, consensus lock, influence edges solidify
                    |
                    +-> Per-agent decisions + public rationales
                    +-> Bracket sentiment distribution
                    +-> Neo4j graph of RationaleEpisodes and INFLUENCED_BY edges
                    +-> ReACT-generated markdown report
                    +-> Live agent interviews (multi-turn Q&A post-simulation)
```

---

## Dashboards

### Web UI (React + TypeScript + FastAPI) - Primary Interface

```bash
npm --prefix frontend ci && npm --prefix frontend run build   # once, and after frontend changes
uv run alphaswarm web
# Open http://localhost:8000
```

| Surface | Description |
|---|---|
| **Influence Graph** | 100 agent nodes in deterministic SVG clusters, color-coded by signal (BUY/SELL/HOLD), with INFLUENCED_BY edges |
| **Control Bar** | Seed input, Start/Stop buttons, live phase indicator, inject-shock drawer |
| **Rationale Feed** | Real-time scrolling stream of agent reasoning with animated entry transitions |
| **Bracket Panel** | Per-archetype sentiment bar charts (D3 SVG) updated after each round |
| **Agent Interview Modal** | Click any agent post-simulation to open a multi-turn Q&A chat panel with restored persona |
| **Replay Mode** | Cycle picker + round-by-round stepping to re-render past simulations from Neo4j (no re-inference) |
| **Report Viewer** | Full-screen modal rendering the ReACT-generated markdown report (sanitized via DOMPurify) |
| **Shock Injection** | Slide-down drawer to inject disruptive events between rounds during a live run |

---

## Agent Archetypes

The swarm models the active price-setting margin of the narrative ecosystem: who
forms and spreads opinions about a rumor. Its 10 brackets are Institutions, Sell-Side,
Event-Driven, Quants, Degens, Narrators, Algos, Macro, Shorts and Allocators. Passive
index capital and market makers are left out on purpose. Counts, reach weights and
prompts live in `DEFAULT_BRACKETS` in `src/alphaswarm/config.py`.

---

## Architecture

```
+----------------------------------------------------------------+
|                         AlphaSwarm                              |
|                                                                 |
|  +--------------+   +--------------+   +------------------+   |
|  |   Ollama     |   |  Simulation  |   |  React + TS SPA  |   |
|  |   27B/35B    |<->|   Engine     |-->|  (D3 viz, agent  |   |
|  |   Models     |   |  (asyncio)   |   |   graph, replay) |   |
|  +--------------+   +------+-------+   |                  |   |
|         ^                  |           +--------^---------+   |
|         |                  v                    | WebSocket + |
|         |           +--------------+            | REST        |
|         |           |    Neo4j     |    +-------+---------+   |
|         |           |  Graph DB    |<-->|    FastAPI      |   |
|         |           |  (Docker)    |    | (broadcaster,   |   |
|         |           +--------------+    |  simulation     |   |
|         |                               |  manager,       |   |
|  +------+----------------------------+  |  replay, report)|   |
|  |      Resource Governor            |  +-----------------+   |
|  |  psutil, dynamic semaphore        |                        |
|  |  throttle @80%, pause @90%        |                        |
|  +-----------------------------------+                        |
+----------------------------------------------------------------+
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ with strict typing |
| Concurrency | `asyncio`, 100% non-blocking, `TaskGroup`-based dispatch |
| Inference | Ollama (default): `qwen3.6:27b-nvfp4` orchestrator, `qwen3.6:35b-a3b-nvfp4` workers; optional cloud via OpenAI-compatible or Anthropic provider |
| Graph State | Neo4j Community: cycle-scoped edges, UNWIND batch writes, async driver |
| Web Backend | FastAPI + `uvicorn`, WebSocket broadcaster @ ~5Hz, drop-oldest backpressure |
| Web Frontend | React + TypeScript + Vite, D3 (d3-scale/selection/transition), `marked` + DOMPurify for report render |
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
| [Node 20+](https://nodejs.org/) | Builds the web UI (required: `frontend/dist/` is not committed) |

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
export ALPHASWARM_NEO4J__PASSWORD="$(openssl rand -hex 32)"
docker compose up -d
```

Neither the container nor the application carries a default Neo4j password.
`docker compose up` aborts when `ALPHASWARM_NEO4J__PASSWORD` is unset or empty,
and the app raises an explicit error instead of opening a Neo4j connection in
the same case. Compose publishes Bolt (7687) and the browser (7474) on
`127.0.0.1` only, so the database is not reachable from your LAN.

Persist the value so every later `docker compose` command and app run can read
it — Compose and the app both read `.env` from the repo root, and `.env` is
gitignored:

```bash
cp .env.example .env   # then set ALPHASWARM_NEO4J__PASSWORD=<the value you generated>
```

Prefer `openssl rand -hex 32`: hex keeps the value clear of `/` (the separator
in `NEO4J_AUTH`) and `$` (special inside `.env` values).

Tests never use this database or password: the Neo4j tests run against a
throwaway `neo4j-test` container on `127.0.0.1:7688`
(`scripts/neo4j_test.sh up`, then `uv run pytest -m neo4j --require-neo4j`).

#### Migrating an existing Neo4j

**If you started it with the old `docker run --name neo4j` recipe.** That
container publishes 7474/7687 on every interface with the old `alphaswarm`
password, and holds those ports, so `docker compose up -d` cannot bind them
until it is gone. Its data also sits on an *anonymous* volume that Compose's
named volume does not adopt — the graph does not carry over on its own. Dump it
first:

```bash
./scripts/backup_neo4j.sh   # writes data/backups/ (set ALPHASWARM_NEO4J_CONTAINER=neo4j if it finds two)
docker rm -f neo4j          # frees the ports and retires the old credential
export ALPHASWARM_NEO4J__PASSWORD="$(openssl rand -hex 32)"
docker compose up -d        # starts alphaswarm-neo4j on 127.0.0.1 with your password
```

To carry the old graph across, load the dump with the restore command the backup
script prints, substituting `alphaswarm-neo4j` for the container name
(`neo4j-admin database load` expects the file named `neo4j.dump` in
`--from-path`). The server you load into must be able to read that store: the
old recipe's floating `neo4j:community` tag is now a 2026.x release while this
repo pins `neo4j:5.26-community`, so if the load is rejected, pin `image:` in
`docker-compose.yml` to the version you dumped from. Credentials are not part of
a database dump — they live in the `system` database — so the restored graph
uses your new password.

**If you were already using `docker compose up -d`.** The named volume is
already initialized, and `NEO4J_AUTH` only takes effect when a volume is
initialized, so a new value in the environment will *not* change the stored
password. Rotate it in place, then recreate the container with the same new
value so its `NEO4J_AUTH` — and the healthcheck derived from it — agree:

```bash
docker exec -it alphaswarm-neo4j \
  cypher-shell -u neo4j -p alphaswarm -d system \
  "ALTER CURRENT USER SET PASSWORD FROM 'alphaswarm' TO '<new-password>'"
export ALPHASWARM_NEO4J__PASSWORD='<new-password>'
docker compose up -d
```

(`docker compose down -v` also works, at the cost of deleting the graph.)

### 4. Run

**Web UI (recommended):**

```bash
npm --prefix frontend ci && npm --prefix frontend run build   # once, and after frontend changes
uv run alphaswarm web                                          # or: uv run start
# Open http://localhost:8000
```

**Other CLI entrypoints:**

```bash
uv run alphaswarm run "Apple acquiring Anthropic for $500B"   # headless sim + markdown report
uv run alphaswarm run "rumor text" --context-fixture <file>   # point-in-time market block, no live fetch
uv run alphaswarm run "rumor text" --no-market-context        # no market block, no live fetch
uv run alphaswarm inject "rumor text"                         # entity extraction only
uv run alphaswarm report --cycle <cycle_id>                   # report for a past cycle (default: latest)
```

### 5. Frontend development (optional)

```bash
cd frontend
npm install
npm run dev    # hot-reload Vite dev server
npm run build  # production build to frontend/dist/
```

---

## Cloud inference (optional)

Local Ollama is the default — no cloud credentials are needed.

To use an API-backed model for the orchestrator, the swarm (worker), or both, open **Settings** in the web UI and choose a provider for each role:

| Provider | When to use |
|---|---|
| **Local (Ollama)** | Default; zero cost, runs entirely on-device |
| **OpenAI-compatible** | OpenAI, OpenRouter, Together, Groq, or any self-hosted vLLM endpoint — set `base_url` + API key |
| **Anthropic** | Native Claude API — set API key only |

The orchestrator and worker roles are configured independently, so you can mix (e.g. local orchestrator + cloud swarm).

Configuration is persisted in `.secrets/inference.json` (gitignored, never logged). The file is created automatically when you save from the Settings UI. You can also edit it by hand:

```json
{
  "orchestrator": {
    "provider": "ollama",
    "model": "alphaswarm-orchestrator",
    "base_url": "http://localhost:11434",
    "api_key": null
  },
  "worker": {
    "provider": "openai_compatible",
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-..."
  },
  "limits": {
    "openai_compatible": { "requests_per_min": 60, "tokens_per_min": 100000 }
  },
  "spend_cap_usd": "5.00",
  "pricing_overrides": {}
}
```

Cloud runs are paced to your provider's RPM/TPM limits via token-bucket rate limiting. A **hard spend cap** (USD) aborts the run gracefully when reached. Before each cloud or mixed run the UI shows a pre-run cost estimate (low / high) and requires confirmation. API keys are redacted from all logs and never returned raw by the API.

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

## What's Shipped

**v1.0 Core Engine:** async batched Ollama inference, dynamic resource governor, Neo4j graph state, 100-agent swarm across 10 brackets, 3-round consensus cascade, dynamic influence topology, and a terminal dashboard (later retired in favour of the web UI).

**v2.0 Engine Depth:** live graph memory (RationaleEpisode nodes, narrative edges), richer agent interactions (public rationale posts, token-budget-aware peer context), dynamic persona generation, post-simulation agent interviews, ReACT-generated markdown reports.

**v3.0 Stock-Specific Recommendations:** ticker extraction, a market-data pipeline and per-ticker decisions. Lost in a bad merge on 2026-04-09; the real-data work was rebuilt differently in v6.0.

**v4.0 Interactive Simulation & Analysis:** shock injection core (disruptive event injection between rounds), shock analysis and reporting, simulation replay from stored Neo4j state.

**v5.0 Web UI:** FastAPI + WebSocket backend, a Vue 3 + D3 single-page app (replaced by the current React + TypeScript UI during v6.0), REST simulation controls + ControlBar, web monitoring panels (rationale feed, bracket charts), replay mode UI, agent interview chat panel, shock injection drawer, browser-based report viewer.

**v6.0 Data Enrichment & Personalized Advisory (in progress):** holdings CSV ingestion, real market data context (yfinance and RSS headlines), optional cloud inference providers, per-archetype data tailoring, and a personalized advisory layer where the orchestrator cross-references swarm consensus against your portfolio with strict information isolation.

---

## License

MIT. See [LICENSE](LICENSE).
