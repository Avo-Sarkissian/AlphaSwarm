# AlphaSwarm Runbook

Operational knowledge from `.planning/` handoffs, debug sessions, and model
decision logs, checked against the scripts and config at commit `820b8fe`.
**README.md already covers** install (`uv sync`), `ollama create` for both
models, first-time Neo4j with `docker compose`, migrating from the old
`docker run` container, the cloud-provider JSON, and governor env vars.
This file covers what README does not, and points to README where they overlap.

---

## 1. Ollama server environment (the most common cause of a slow simulation)

AlphaSwarm's throughput depends on Ollama **server** environment variables.
`ALPHASWARM_OLLAMA__NUM_PARALLEL` and `ALPHASWARM_OLLAMA__MAX_LOADED_MODELS`
in `.env` are dead config: the app never reads them (`config.py:40-41`).

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `4` | 16 spilled about 103 GB of KV cache to CPU on the M1 Max (2026-05-06 probe). 4 keeps prefill overlap |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Worker plus orchestrator; CLAUDE.md hard constraint |
| `OLLAMA_KEEP_ALIVE` | `5m` | Keeps the worker warm between rounds |
| `OLLAMA_USE_MLX` | `1` | Required for the nvfp4 models. Without it Ollama **silently** uses llama.cpp |

**Ollama.app (normal case):**
```bash
./scripts/configure_ollama_app_env.sh
pkill -TERM -f "Ollama.app/Contents/MacOS/Ollama"; sleep 3; open -a Ollama
```
This runs `launchctl setenv` and also installs the LaunchAgent
`~/Library/LaunchAgents/com.alphaswarm.ollama-env.plist` (RunAtLoad), because
**`launchctl setenv` does not survive a reboot.** A reboot once left the swarm
running serially for weeks. The script header has the commands to reverse it.

**Terminal `ollama serve`:** `./scripts/start_ollama.sh`. It exports
`OLLAMA_USE_MLX=1`, `OLLAMA_NUM_PARALLEL=4` and `OLLAMA_MAX_LOADED_MODELS=2`;
any of them already set in your shell wins.

**Verify what the running server actually has:**
```bash
ps eww $(pgrep -f "ollama serve") | tr ' ' '\n' | grep '^OLLAMA_'
launchctl getenv OLLAMA_NUM_PARALLEL   # what the app will get on next launch
```

## 2. Models

Code always calls the **aliases** `alphaswarm-worker` and
`alphaswarm-orchestrator` (`config.py:48-49`). The Modelfile `FROM` line decides
which model actually runs. Changing `ALPHASWARM_OLLAMA__WORKER_MODEL` changes
only the CLI banner.

```bash
ollama pull qwen3.6:35b-a3b-nvfp4     # worker base (about 22 GB, MLX)
ollama pull qwen3.6:27b-nvfp4         # orchestrator base (about 20 GB, MLX)
ollama create alphaswarm-worker -f modelfiles/Modelfile.worker
ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator
ollama show alphaswarm-worker --modelfile | head -5      # confirm FROM + params
```

- **Re-run `ollama create` after any Modelfile edit.** For example,
  `num_predict 400`, which caps runaway 14-20 minute generations. Code changes
  do not reach the model until you do.
- `num_ctx` belongs only in Modelfiles (worker 4096, orchestrator 8192).
  `OllamaClient` strips it from requests, because a per-request `num_ctx` makes
  Ollama silently reload the model.
- Reasoning is on by default in qwen3.6. Every call site passes `think=False`
  (DECISIONS#adr-think-off).
- **Rollback options:** `qwen3.5:35b` (GGUF MoE), or `qwen3:8b` worker plus
  `qwen3.6:27b-q4_K_M` orchestrator. Edit `FROM`, re-run create, and expect
  slower prefill. Avoid IQ4_XS quants on Apple Silicon (about 3.8× slower Metal
  kernels).

### MLX engagement check
```bash
grep "MLX engine initialized" ~/.ollama/logs/server.log | tail -3
```
- MLX engages only for MLX-format tags (`nvfp4`, `mxfp8`, `mlx-*`) and only
  with `OLLAMA_USE_MLX=1` and at least 32 GB. GGUF tags always use llama.cpp.
- The **first call after a load pays kernel compilation** (about 10× slower
  prefill). When benchmarking, time the second call.
- The MLX runner follows the prompt more than a hard grammar for `format=schema`,
  so keep the explicit key list in prompts and keep the 3-tier parser.
- Reference numbers (2026-06-11, Ollama 0.30.7, this machine):
  - Worker: prefill about 2361 t/s, decode about 56 t/s.
  - Orchestrator: prefill about 3395 t/s, decode about 11 t/s.

## 3. Neo4j operations (beyond README §3)

- Compose service `neo4j`, container `alphaswarm-neo4j`, image
  `neo4j:5.26-community`, bound to 127.0.0.1 only. The password comes from
  `ALPHASWARM_NEO4J__PASSWORD`, which `docker compose` reads from `.env`.
- **Back up before risky work, and weekly:** `./scripts/backup_neo4j.sh`.
  - It stops the container briefly, so don't run it mid-simulation.
  - It writes `data/backups/neo4j-<stamp>.dump` and keeps the 8 newest.
    `data/backups/` is **not** gitignored today (BACKLOG 1.12), so never
    `git add -A` after a backup until that is fixed.
  - It refuses to guess if both `alphaswarm-neo4j` and a legacy `neo4j`
    container exist. Set `ALPHASWARM_NEO4J_CONTAINER=<name>` in that case.
- **Restore** (the command the script prints needs one extra step, BACKLOG 1.6).
  `neo4j-admin database load` only reads a file named `neo4j.dump`:
  ```bash
  mkdir -p /tmp/as-restore && cp data/backups/neo4j-<stamp>.dump /tmp/as-restore/neo4j.dump
  IMG=$(docker container inspect --format '{{.Image}}' alphaswarm-neo4j)
  docker stop alphaswarm-neo4j
  docker run --rm --volumes-from alphaswarm-neo4j -v /tmp/as-restore:/backups "$IMG" \
    neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true
  docker start alphaswarm-neo4j
  ```
- **Tests never use this database.** Neo4j tests run against the throwaway
  `neo4j-test` container (`127.0.0.1:7688`, tmpfs, credential
  `neo4j/alphaswarm-test-only`): `scripts/neo4j_test.sh up`, then
  `uv run pytest -q -m neo4j --require-neo4j`, then `scripts/neo4j_test.sh down`.
  The fixture refuses port 7687 and any database that already holds cycles; if it
  reports leftover cycles, run `scripts/neo4j_test.sh reset`.
- Useful Cypher in the browser (http://127.0.0.1:7474):
  ```cypher
  MATCH (c:Cycle) RETURN c.cycle_id, c.created_at, c.num_rounds, c.metrics_recorded_at ORDER BY c.created_at DESC LIMIT 10;
  MATCH (c:Cycle {cycle_id:$id}) RETURN c;   // run metrics: durations, flips, parse errors, final distribution
  ```
- Compare runs: `uv run python scripts/compare_cycles.py --limit 5`.
  It builds `AppSettings()` (`scripts/compare_cycles.py:44`), which reads
  `.env` from the current directory, so run it from the repo root.

## 4. Running the stack for development

```bash
# Terminal 1: backend. Start it FROM THE REPO ROOT. These paths are all
# relative to the working directory: .env (AppSettings env_file), the holdings
# CSV (Schwab/holdings.csv), .secrets/inference.json, and the advisory/ and
# reports/ output dirs.
uv run uvicorn alphaswarm.web.app:app --port 8000      # or ./start (cds to the repo root, then python -m alphaswarm web)
# Note: `uv run start` (cli:main_web) does NOT cd, so it uses whatever directory you are in.

# Terminal 2: frontend with hot reload (proxies /api and /ws to :8000)
npm --prefix frontend run dev                           # http://localhost:5173
```
- `http://localhost:8000` serves the UI **only after** `npm --prefix frontend run build`.
  `frontend/dist/` is gitignored, so build it first (README Quick Start). Without a build, use :5173.
- Uvicorn does not hot-reload Python changes in this setup. **Restart the
  backend** after backend edits, and hard-refresh the browser for frontend edits.
- Fast smoke runs: `ALPHASWARM_NUM_ROUNDS=2`. The UI still shows "/3"
  (BACKLOG 1.4).
- Headless run with live progress output: `uv run python -m alphaswarm run "<rumor>"`.
  It honors `.secrets/inference.json` since 342b285.

### Cloud mode quick reference
- Provider config lives in `.secrets/inference.json` (gitignored). Edit it through
  Settings or `PUT /api/settings`. Delete it to fall back to local Ollama.
- NVIDIA NIM free tier (`https://integrate.api.nvidia.com/v1`):
  - Models: worker `meta/llama-3.1-8b-instruct`, orchestrator `meta/llama-3.3-70b-instruct`.
  - Limits: `requests_per_min: 40`, `max_in_flight: 1`, `max_retries: 8`. The tier
    returns 429 with no Retry-After at about 40 RPM.
  - Avoid reasoning models: they blow the token cap and break JSON mode.
- `/api/health` reports `inference_mode` and running `spent_usd`.

## 5. Full-run smoke / UAT checklist

**Readiness check:**
```bash
curl -s -o /dev/null -w "api %{http_code}\n" http://localhost:8000/api/health
curl -s http://localhost:8000/api/holdings | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["holdings"]),"positions") if "holdings" in d else print("FAILED:",d)'
curl -s -o /dev/null -w "vite %{http_code}\n" http://localhost:5173
curl -s -o /dev/null -w "ollama %{http_code}\n" http://localhost:11434/api/version
docker compose ps        # neo4j healthy
grep "MLX engine initialized" ~/.ollama/logs/server.log | tail -1
```

**Run a cycle.** Use a benchmark seed from `scripts/benchmark_seeds.json`; one
that names a held company exercises the advisory. Then check:

- [ ] Dots appear within about 30 s of Round 1 and fill in progressively, with dim "thinking" dots for agents still working. At a round change, dots do not vanish.
- [ ] KPI strip ticks (5 Hz). PARALLEL SLOTS shows live used/max. RAM% is non-zero even when idle.
- [ ] Rationale feed fills live during the round, and R3 entries remain after completion.
- [ ] Signal Wire shows real yfinance/RSS calls, not the DEV mock seed.
- [ ] Bracket bars update after each round.
- [ ] After completion:
  - Top Influencers switches to OUT-DEGREE with no "0" filler rows (F-35).
  - The top strip shows "N active edges".
  - `/api/edges/<cycle>?round=3` is non-empty.
- [ ] Advisory auto-fires. The server log shows `auto_advisory_trigger_accepted`, and `advisory/<cycle>_advisory.json` appears.
- [ ] AdvisoryV2 has one row per holding, and the Overview tiles show real values.
- [ ] The report then auto-generates at `reports/<cycle>_report.md`. It contains global consensus **and** signal-flip sections (F-06), a minority of dissenters rather than all 100 (F-01), and only real flips (F-02). The "social post reach" section is currently empty (BACKLOG 1.1).
- [ ] InterviewV2 gives a real answer from `/api/interview/<agent>`.
- [ ] Replay: start a past cycle; frames keep streaming (F-24); Forward stops at the cycle's real depth (F-12); live start is blocked during replay (B4).
- [ ] CycleHistory, Settings, Data Sources, and BracketDeepDive open as styled full-screen takeovers.
- [ ] Double-clicking Run starts once (F-33).
- [ ] Onboarding: stop the backend, clear `localStorage` key `as_onboarding_v1_complete`, and confirm the final step's run button is disabled and reads "Start backend first" (`onboarding.tsx:256-264`).
- [ ] Governor warning: when `governor_state` is `paused` or `crisis`, a dismissible banner appears over the dashboard (`app_v2.tsx:238-246, 552-554`). There is no way to force it from the UI: the DEV tweaks "Demo state → Mem ceiling" button is a no-op, and the old full-screen `MemoryPausedState` is dead code (BACKLOG 2.2).
- [ ] If a shock is injected: the report's shock-impact section shows non-zero percentages and arrows (F-03).
- [ ] `uv run python scripts/compare_cycles.py --limit 1` shows the new cycle's metrics. `r*_parse_errors` should be low.

**Fast checks (no services needed):**
```bash
uv run pytest -q -m "not neo4j" --ignore=tests/test_integration_inference.py
                          # the ignore mirrors CI; Neo4j tests need neo4j-test (Neo4j section
                          # above). tests/integration hits the network (BACKLOG 1.8). iCloud
                          # conflict copies ("app 2.py") are gitignored and skipped by
                          # the --ignore-glob in pyproject addopts (BACKLOG §8, B2)
cd frontend && npx tsc -b --noEmit && npx vitest run && npm run build
uv run lint-imports       # holdings isolation contract: must report "kept"
```

## 6. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Simulation suddenly much slower; agents seem to run one at a time | Ollama env lost after a reboot, or MLX not engaged | §1 `ps eww …`, then re-run `configure_ollama_app_env.sh` and relaunch Ollama. Check the MLX grep in §2. Confirm `ollama ps` shows the nvfp4 alias |
| Individual calls take minutes, or one agent hangs | Runaway generation, or a model swap thrash | `num_predict 400` must be in the registered worker (`ollama show …`). The client timeout (600 s) turns a hang into PARSE_ERROR. Check that `ollama ps` holds no more than 2 models |
| UI frozen, elapsed timer still ticking | WebSocket not connected | DevTools → WS: expect `101` on `/ws/state`. Vite proxy needs `changeOrigin: true` (present in `frontend/vite.config.ts`). A close code **1008** means the page origin is not in `ALPHASWARM_WS_ALLOWED_ORIGINS`; add it, for example a LAN address |
| `403` on POST/PUT from the UI | Origin guard on state-changing routes | Add the serving origin to `ALPHASWARM_HTTP_ALLOWED_ORIGINS` (JSON list) |
| `/api/holdings` → `holdings_unavailable` (503); advisory never appears | Backend started from the wrong directory (for example `frontend/`, or `uv run start` from elsewhere), or the CSV is missing or malformed | `lsof -a -d cwd -p "$(lsof -ti tcp:8000 -sTCP:LISTEN)"` must show the repo root (works for `uvicorn`, `./start`, and `uv run start`). Or set `ALPHASWARM_HOLDINGS_CSV_PATH` to an absolute path. A wrong directory also loses `.env` and `.secrets/inference.json` |
| Advisory returns 404 for a long time | Still generating (404 is the "pending" contract) | Watch the server log for `advisory_generation_complete`. Post-run narratives (100 worker calls) and the model swap run first |
| Report, advisory, or interview returns `409 report_unavailable` / `advisory_unavailable` / `interview_unavailable` | Phase gate: in-memory phase is not COMPLETE, for example after a backend restart | Known limitation (BACKLOG 1.3). Use the CLI `uv run python -m alphaswarm report --cycle <cycle_id>` for historical cycles. |
| `409 *_generation_in_progress` | The other orchestrator job (report/advisory) is running | Wait. The two jobs are serialized on purpose |
| Graph empty during a round | Backend not streaming per-agent state, or an older backend still running | Restart the backend. Confirm `agent_states` keys in a WS frame |
| Neo4j auth error at startup | `ALPHASWARM_NEO4J__PASSWORD` unset, or it differs from the initialized volume | README §3 "Migrating". `NEO4J_AUTH` only applies when a volume is first initialized |
| `pytest` Neo4j tests all skipped | neo4j-test is not running | `scripts/neo4j_test.sh up`; add `--require-neo4j` to make a missing database fail instead of skip |
| pytest exits with code 3 ("Refusing to run Neo4j tests") | neo4j-test holds leftover cycles from a crashed session, or something else answers on 7688 | `scripts/neo4j_test.sh reset` |
| Replay or history list empty | No metric-stamped cycles, or history wiped | `MATCH (c:Cycle) WHERE c.metrics_recorded_at IS NOT NULL RETURN count(c)`. Restore from `data/backups/` |
| Cloud run: many PARSE_ERRORs or 429s | Provider rate limit | Lower `requests_per_min`, set `max_in_flight: 1`, raise `max_retries` (see §4 cloud) |
| `GovernorCrisisError` | Sustained macOS memory pressure (5 min with no successful inference) | Close memory-heavy apps. Check that `ollama ps` shows only 2 models. Lower `ALPHASWARM_GOVERNOR__BASELINE_PARALLEL` |
