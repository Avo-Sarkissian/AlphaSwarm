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
The app has no setting for these: they are Ollama server variables. Old `.env` lines
`ALPHASWARM_OLLAMA__NUM_PARALLEL` / `ALPHASWARM_OLLAMA__MAX_LOADED_MODELS` are ignored with a warning.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `4` | 16 spilled about 103 GB of KV cache to CPU on the M1 Max (2026-05-06 probe). 4 keeps prefill overlap |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Worker plus orchestrator; CLAUDE.md hard constraint |
| `OLLAMA_KEEP_ALIVE` | `5m` | Keeps the worker warm between rounds |
| `OLLAMA_USE_MLX` | `1` | Required for the nvfp4 models. Without it Ollama **silently** uses llama.cpp |

App-side timeouts (`.env`, see `.env.example`): `ALPHASWARM_OLLAMA__CONNECT_TIMEOUT_S=5`,
`ALPHASWARM_OLLAMA__WORKER_READ_TIMEOUT_S=120`, `ALPHASWARM_OLLAMA__ORCHESTRATOR_READ_TIMEOUT_S=600`
(`docs/DECISIONS.md#adr-inference-timeouts`). The old `ALPHASWARM_OLLAMA__REQUEST_TIMEOUT_SECONDS`
still works, mapped to the orchestrator value with a warning; rename it.

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
`alphaswarm-orchestrator` (`settings.py:OllamaSettings`). The Modelfile `FROM` line decides
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
- Both Modelfiles set `num_predict` as a fallback only; call sites pass their
  own caps (`src/alphaswarm/inference/caps.py`).
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
- Every model load logs `model_warmed` with `prefill_tps`; a `model_warmup_slow`
  warning on a warm-up means the prefill rate looks like the llama.cpp
  fallback: run the check above.
- The MLX runner follows the prompt more than a hard grammar for `format=schema`,
  so keep the explicit key list in prompts and keep the 3-tier parser.
- Reference numbers (2026-06-11, Ollama 0.30.7, this machine):
  - Worker: prefill about 2361 t/s, decode about 56 t/s.
  - Orchestrator: prefill about 3395 t/s, decode about 11 t/s.

### SEC ticker map (seed-entity tickers)
The swarm validates orchestrator-proposed tickers against the SEC company map cached at
`data/sec_tickers.json` (gitignored; `ALPHASWARM_TICKER_MAP_PATH` overrides). Fetch or refresh it once:

    uv run python scripts/fetch_ticker_map.py --user-agent "AlphaSwarm research <your email>"

The SEC asks automated clients to name a contact in the User-Agent; it is sent in that one request
only. Without the file the resolver still drops known non-company acronyms (FED, OPEC, …) but
trusts every other proposed symbol; check `ticker_map_loaded source=sec` in the run log.

## 3. Neo4j operations (beyond README §3)

- Compose service `neo4j`, container `alphaswarm-neo4j`, image
  `neo4j:5.26-community`, bound to 127.0.0.1 only. The password comes from
  `ALPHASWARM_NEO4J__PASSWORD`, which `docker compose` reads from `.env`.
- **Back up before risky work, and weekly:** `./scripts/backup_neo4j.sh`.
  - It refuses to run while a simulation is running (the web server's `/api/health` says `is_simulation_running`, or a CLI `run`/`inject`/`report` holds the instance lock) and exits 75; otherwise it stops the container with a 60 s grace period and always restarts it. `ALPHASWARM_BACKUP_DIR` writes the dump elsewhere.
  - It writes `data/backups/neo4j-<stamp>.dump` and keeps the 8 newest.
    `data/backups/` is **not** gitignored today (BACKLOG 1.12), so never
    `git add -A` after a backup until that is fixed.
  - It finds the container by name: `alphaswarm-neo4j` (Compose) or `neo4j`
    (a hand-made `docker run --name neo4j` container). It refuses to guess if
    both exist; set `ALPHASWARM_NEO4J_CONTAINER=<name>` in that case (or always,
    to be explicit: `ALPHASWARM_NEO4J_CONTAINER=neo4j ./scripts/backup_neo4j.sh`).
- **Restore.** The script prints a working sequence after every backup, with
  the real dump path, container and image filled in; it is the same as
  (`<container>` is `alphaswarm-neo4j` or `neo4j`):
  ```bash
  RESTORE_DIR="$(mktemp -d)"
  cp data/backups/neo4j-<stamp>.dump "$RESTORE_DIR/neo4j.dump"   # neo4j-admin only loads neo4j.dump
  IMG=$(docker container inspect --format '{{.Image}}' <container>)
  docker stop -t 60 <container>
  docker run --rm --volumes-from <container> -v "$RESTORE_DIR":/backups "$IMG" \
    neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true
  docker start <container>
  ```
  Never restore while a simulation runs. `tests/test_backup_script.py` replays
  the printed sequence against a fake `docker`; verify it once on a scratch
  container before relying on it.
- **Memory caps (2026-10).** The Compose `neo4j` service runs with a 1 GB heap,
  512 MB page cache, 512 MB transaction memory, `mem_limit: 2500m`,
  `stop_grace_period: 60s` and `-XX:+ExitOnOutOfMemoryError`. Check with
  `docker stats --no-stream alphaswarm-neo4j` (usage stays below 2.44 GiB) and
  give Docker Desktop 3-4 GiB of memory. A hand-made container (for example one
  named `neo4j`, created with `docker run`) does not read the Compose file: the
  container limit can be applied in place with
  `docker update --memory 2500m --memory-swap 2500m <name>`, but the heap and
  page-cache settings are environment variables fixed at creation, so they need
  a backup, then a recreate with the same volume plus
  `-e NEO4J_server_memory_heap_initial__size=1g -e NEO4J_server_memory_heap_max__size=1g`
  `-e NEO4J_server_memory_pagecache_size=512m -e NEO4J_db_memory_transaction_total_max=512m`
  `-e JDK_JAVA_OPTIONS=-XX:+ExitOnOutOfMemoryError --memory 2500m --stop-timeout 60`.
  Shrinking the governor's slots barely changes the models' footprint (server
  parallelism is fixed by `OLLAMA_NUM_PARALLEL`); the governor prevents stalls,
  it is not a memory lever.
- **Retired properties (one-off, optional):** narratives now live on each cycle's
  final-round Decision, and nothing reads the old `Agent.decision_narrative`
  property. Startup never removes it (`GraphStateManager.remove_legacy_properties()` does,
  and nothing calls it automatically). To drop it, back up first, then run in the Neo4j browser:
  `MATCH (a:Agent) WHERE a.decision_narrative IS NOT NULL REMOVE a.decision_narrative`.
- **Tests never use this database.** Neo4j tests run against the throwaway
  `neo4j-test` container (`127.0.0.1:7688`, tmpfs, credential
  `neo4j/alphaswarm-test-only`): `scripts/neo4j_test.sh up`, then
  `uv run pytest -q -m neo4j --require-neo4j`, then `scripts/neo4j_test.sh down`.
  The fixture refuses port 7687 and any database that already holds cycles; if it
  reports leftover cycles, run `scripts/neo4j_test.sh reset`.
- Useful Cypher in the browser (http://127.0.0.1:7474):
  ```cypher
  MATCH (c:Cycle) RETURN c.cycle_id, c.created_at, c.status, c.error_code, c.num_rounds ORDER BY c.created_at DESC LIMIT 10;
  MATCH (c:Cycle {cycle_id:$id}) RETURN c;   // run metrics: durations, flips, parse errors, final distribution
  ```
- Compare runs: `uv run python scripts/compare_cycles.py --limit 5`. It lists
  complete cycles only, by the same status rule as the replay picker.
  It builds `AppSettings()` (`scripts/compare_cycles.py:56`), which reads the
  repo root's `.env` whatever the current directory.

## 4. Running the stack for development

- **One AlphaSwarm process at a time.** `alphaswarm web` (or `./start`) holds `~/.alphaswarm/instance.lock`; `alphaswarm run`, `inject` or `report` started meanwhile exit with code 75 and name the holder. Run jobs from the web UI while the server is up. `alphaswarm doctor` never takes the lock. A crashed process releases it automatically.

```bash
# Terminal 1: backend. Runtime paths (.env, holdings CSV, .secrets/, advisory/, reports/) resolve against the repo root, so any working directory works.
uv run alphaswarm web      # the single launcher (127.0.0.1:8000); ./start and uv run start call it

# Terminal 2: frontend with hot reload (proxies /api and /ws to :8000)
npm --prefix frontend run dev                           # http://localhost:5173
```
- `./start` and `alphaswarm web` configure logging before uvicorn starts, so every
  server line, uvicorn's own included, goes through the redacting structlog chain.
  A direct `uv run uvicorn --factory alphaswarm.web.app:create_app --port 8000` also works, but its
  first two lines ("Started server process", "Waiting for application startup.")
  use uvicorn's own format; the app takes over uvicorn's loggers when its lifespan
  starts.
- `http://localhost:8000` serves the UI **only after** `npm --prefix frontend run build`.
  `frontend/dist/` is gitignored, so build it first (README Quick Start). Without a build, use :5173.
- Uvicorn does not hot-reload Python changes in this setup. **Restart the
  backend** after backend edits, and hard-refresh the browser for frontend edits.
- With the backend stopped, actions on :5173 show "Cannot reach the backend. Is it running
  on port 8000?": the dev proxy answers 502 `backend_unreachable` and logs `http proxy error`.
- Fast smoke runs: `ALPHASWARM_NUM_ROUNDS=2`. The UI follows the frame's `num_rounds`.
- Private-headline experiment: `ALPHASWARM_SIMULATION__PRIVATE_HEADLINES=true` gives each agent a seeded half of each entity's headlines (prices shared). Experiment runs only; never the default (`docs/DECISIONS.md#p40-d-07`).
- Headless run with live progress output: `uv run python -m alphaswarm run "<rumor>"`.
  It honors `.secrets/inference.json` since 342b285.

### Cloud mode quick reference
- Provider config lives in `.secrets/inference.json` (gitignored). Edit it through
  Settings or `PUT /api/settings`. Move it aside (or delete it) to fall back to local
  Ollama. The file is strict: an unknown key or an out-of-range limit makes it
  invalid; it is never rewritten automatically, and `/api/health` shows it as the
  `inference_config` component.
- NVIDIA NIM free tier (`https://integrate.api.nvidia.com/v1`):
  - Models: worker `meta/llama-3.1-8b-instruct`, orchestrator `meta/llama-3.3-70b-instruct`.
  - Limits: `requests_per_min: 40`, `max_in_flight: 1`, `max_retries: 8`. The tier
    returns 429 with no Retry-After at about 40 RPM.
  - Avoid reasoning models: they blow the token cap and break JSON mode.
- `/api/health` reports `inference_mode` and running `spent_usd`.
- Retries (`docs/DECISIONS.md#adr-cloud-retry`): 408/409/429/5xx retry with capped jittered backoff (at most 30 s per wait; `Retry-After` honoured up to 60 s), and a 429 pauses every agent once (one shared cooldown). 400/404/422 and timeouts are not retried: a wrong model id stops the run before seeding with "The … provider rejected model …" (CLI exit 2).
- `limits.<provider>.avg_tokens_per_call` (default 1500) is the TPM reservation per call; lower it toward your real prompt size if `tokens_per_min` throttles too early.
- Free models (the NVIDIA NIM free tier) are not in the pricing table. With a spend cap set they are priced at the conservative ceiling, so add `pricing_overrides` entries with `"0"` prices or leave the cap unset. `GET /api/settings/estimate` lists them in `unpriced_models`.
- `DEFAULT_PRICING` is re-checked against the vendor pages at least every 180 days: `PRICING_VERIFIED_AT` in `inference/budget.py`, and `tests/inference/test_budget.py::TestPricingTable::test_pricing_table_was_verified_recently` fails when it is stale.

## 5. Full-run smoke / UAT checklist

**Readiness check:**
```bash
curl -s http://localhost:8000/api/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print("api", d["status"]); [print("  %s: %s" % (n, "ok" if c["ok"] else "down (%s), not required" % c["detail"] if not c["required"] else "DOWN (%s); fix: %s" % (c["detail"], c["fix"]))) for n, c in d["components"].items()]'
curl -s http://localhost:8000/api/holdings | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["holdings"]),"positions") if "holdings" in d else print("FAILED:",d)'
curl -s -o /dev/null -w "vite %{http_code}\n" http://localhost:5173
curl -s -o /dev/null -w "ollama %{http_code}\n" http://localhost:11434/api/version
docker compose ps        # neo4j healthy (docker ps for a container you created yourself)
grep "MLX engine initialized" ~/.ollama/logs/server.log | tail -1
```

Expect `api ok`. A component that is down but not required (Ollama and the
aliases when both roles are cloud) does not degrade it. The `inference_config`
component is always required and read fresh on every request: `DOWN (rejected: ...)`
names the rejected keys and error types (never values). `/api/health` answers 200
even when it is `degraded`, so read the status, not the HTTP code; each `DOWN`
line prints its fix. `/api/health/live` only says the process answers.

**Run a cycle.** Use a benchmark seed from `scripts/benchmark_seeds.json`; one
that names a held company exercises the advisory. Then check:

- [ ] Dots appear within about 30 s of Round 1 and fill in progressively, with dim "thinking" dots for agents still working. At a round change, dots do not vanish.
- [ ] KPI strip ticks (5 Hz). PARALLEL SLOTS shows live used/max. RAM% is non-zero even when idle.
- [ ] Rationale feed fills live during the round, and R3 entries remain after completion.
- [ ] During R3, DevTools → Network shows `/api/edges/<this run's cycle_id>?round=2`, never the previous cycle's id.
- [ ] Restart the backend: the dashboard shell (Settings, replay, reports) is usable while idle.
- [ ] Press Run while the report is generating: the button reads "Report generating…" and is disabled.
- [ ] Signal Wire shows real yfinance/RSS calls, not the DEV mock seed.
- [ ] Bracket bars fill in live during each round (pending agents leave the bar blank). At each round start the ring reads PENDING and the KPI "0/100 decided", never "HOLD 100%".
- [ ] After completion:
  - Top Influencers reads CITED BY and ranks by citations received.
  - The top strip shows "N active edges".
  - `/api/edges/<cycle>?round=3` is non-empty.
- [ ] The post-run pipeline runs. With holdings loaded, `advisory/<cycle>_advisory.json` appears first; the server log then shows `post_run_pipeline_completed` with `report=ran` (and `advisory=ran`, or a `skipped_*` value naming why the advisory did not run).
- [ ] AdvisoryV2 has one row per holding, and the Overview tiles show real values.
- [ ] The report then auto-generates at `reports/<cycle>_report.md`. It contains global consensus **and** signal-flip sections (F-06), a minority of dissenters rather than all 100 (F-01), and only real flips (F-02). The "social post reach" section is currently empty (BACKLOG 1.1).
- [ ] InterviewV2 gives a real answer from `/api/interview/<agent>`.
- [ ] Replay: start a past cycle; frames keep streaming (F-24); Forward stops at the cycle's real depth (F-12); live start is blocked during replay (B4). Reload the page during replay: the bar is still there and Exit replay works.
- [ ] CycleHistory, Settings, Data Sources, and BracketDeepDive open as styled full-screen takeovers.
- [ ] Double-clicking Run starts once (F-33).
- [ ] Onboarding. `/api/health` caches its Neo4j, Ollama and alias probes for 5 s, so those components can be up to 5 s old (the `inference_config` component is read fresh on every request): when a Re-check still shows the previous state, wait 5 s and press Re-check again.
  - Stop Neo4j (`docker compose stop neo4j`, or `docker stop <name>` for a container you created yourself), clear the `localStorage` key `as_onboarding_v1_complete` and reload the page.
  - Click "Get started" and type a seed of at least 10 characters (or click an example). The step lists `neo4j` with its fix, and the run button reads "Fix the items above first" and stays disabled.
  - Start Neo4j again (`docker compose start neo4j`, or `docker start <name>`) and wait until it accepts connections, which takes several seconds: `docker compose ps` shows it `healthy`, or `docker logs <name>` ends with `Started.` for your own container. Press Re-check: the status reads "Backend ready" and "Run first cycle" is enabled.
  - Stop the backend and press Re-check: the status reads "Backend unreachable" and the button "Start backend first". Start the backend again before the next check.
- [ ] Governor warning: when `governor_state` is `paused` or `crisis`, a dismissible banner appears over the dashboard (`app_v2.tsx:255-263, 477-503`). There is no way to force it from the UI; the DEV tweaks panel and the old full-screen `MemoryPausedState` were deleted (2026-10).
- [ ] If a shock is injected: the report's shock-impact section shows non-zero percentages and arrows (F-03).
- [ ] `uv run python scripts/compare_cycles.py --limit 1` shows the new cycle's metrics. `r*_parse_errors` should be low.
- [ ] After the run: `uv run python scripts/telemetry_report.py rows --cycle <cycle id>` shows prefill, decode and load per round; `docs/experiments.md` has the protocol for comparisons.

**Fast checks (no services needed):**
```bash
uv run pytest -q -m "not neo4j and not live_network and not ollama"
                          # offline, same selection as CI backend-unit; Neo4j tests need neo4j-test
                          # (Neo4j section above), live tests need --run-live (§7). iCloud
                          # conflict copies ("app 2.py") are gitignored and skipped by
                          # the --ignore-glob in pyproject addopts (BACKLOG §8, B2)
uv run pytest -q tests/engine -rxX
                          # the real run_simulation on scripted fakes, about 2 s; XFAIL
                          # lines are pinned engine bugs (DECISIONS#adr-engine-scenario-harness)
(cd frontend && npx tsc -b --noEmit && npx vitest run && npm run lint && npm run build)
                          # npm run lint is ESLint: 0 errors required (frontend/TESTING.md)
uv run lint-imports       # every contract must report "KEPT": holdings isolation and
                          # acyclic siblings (no import cycles between alphaswarm modules)
uv run mypy src           # strict; must report "Success: no issues found"
uv run ruff check src tests && uv run ruff format --check src tests
                          # 120 columns; the pre-commit hooks fix most findings
```

## 6. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Slow or failing calls, or a reply cut short | An output cap, or one slow phase (prefill, decode, load) | `grep '"inference_call"'` in the backend log: one line per provider call (tokens, prefill/decode/load ms, `finish_reason`, latency). `finish_reason` `"length"` or a `decision_truncated` warning means a reply hit its output cap |
| UI silent while the backend runs | The broadcaster is not sending | `grep '"broadcast_stats"'` in the backend log: `serializations` should follow the client count (0 with no client, about 60 a minute per idle client, more while state changes) |
| Simulation suddenly much slower; agents seem to run one at a time | Ollama env lost after a reboot, or MLX not engaged | §1 `ps eww …`, then re-run `configure_ollama_app_env.sh` and relaunch Ollama. Check the MLX grep in §2. Confirm `ollama ps` shows the nvfp4 alias |
| Individual calls take minutes, or one agent hangs | Runaway generation, or a model swap thrash | `num_predict 400` must be in the registered worker (`ollama show …`). The worker read timeout (120 s; the orchestrator's is 600 s) turns a hang into PARSE_ERROR. Check that `ollama ps` holds no more than 2 models |
| UI frozen, elapsed timer still ticking | WebSocket not connected | DevTools → WS: expect `101` on `/ws/state`. Vite proxy needs `changeOrigin: true` (present in `frontend/vite.config.ts`). Close code **1008** means the page origin is not in `ALPHASWARM_ALLOWED_ORIGINS`; an HTTP **400** on the handshake means the Host is not in `ALPHASWARM_TRUSTED_HOSTS` |
| `403 origin_not_allowed` on POST/PUT from the UI | Origin guard on state-changing routes | Add the serving origin to `ALPHASWARM_ALLOWED_ORIGINS` (JSON list) |
| `400 Invalid host header` | The UI was opened under a name other than `localhost`/`127.0.0.1` (a LAN IP, `0.0.0.0`, a `.local` name) | Use `http://localhost:8000`, or add the name to `ALPHASWARM_TRUSTED_HOSTS` and its origin to `ALPHASWARM_ALLOWED_ORIGINS`, then restart |
| `/api/holdings` → `holdings_unavailable` (503); advisory never appears | The CSV is missing, not UTF-8, or malformed (empty symbol, NaN/infinite/negative numbers) | A missing file logs no `holdings_load_failed`, and no log line names the path: check that `ALPHASWARM_HOLDINGS_CSV_PATH` (default `Schwab/holdings.csv`, resolved against the repo root) names an existing file. The setting is read at startup, so restart the server after changing it in `.env`. For a file that exists, `holdings_load_failed` in the server log gives the reason (and the row number for a bad row); fix the file: it is re-read when it changes, no restart needed. See `examples/holdings.example.csv` |
| Advisory GET returns 409 `advisory_generation_in_progress` | Generating | Wait; 404 now means no advisory exists (no holdings, or the run or the advisory job has not finished yet) |
| Advisory GET returns 500 `cloud_advisory_disabled` or `inference_config_invalid` | The orchestrator is a cloud or remote model without `allow_cloud_advisory`, or the inference config cannot be read. The advisory was refused (after a run, the report still runs) | Switch the orchestrator to a local Ollama model, or tick **Allow cloud advisory** in Settings → Model. The checkbox is shown for an orchestrator that looks cloud or remote from its settings; when it is not shown (an alias of an Ollama cloud model, a remote `OLLAMA_HOST`), set `allow_cloud_advisory` to `true` in `.secrets/inference.json`. For an invalid config, see the next row |
| Settings shows "Failed to load inference settings" (422 `inference_config_invalid`) | The stored inference config (`ALPHASWARM_INFERENCE_CONFIG_PATH`, default `.secrets/inference.json`) is not valid JSON or no longer matches the config model. Settings can neither load it nor save over it | `GET /api/health` → `components.inference_config.detail` lists the rejected keys (no values), or reads `unreadable (<error type>)` when the file cannot be read (for example its permissions). Fix the file by hand, or move it aside (the local defaults apply without it), then reopen Settings and save again. It holds API keys: never paste its contents into an issue or a log |
| A run stops at once with `inference_config_invalid` ("The saved inference configuration is incomplete …") while `/api/health` shows `inference_config` ok | The file loads, but a cloud role has no API key, or an OpenAI-compatible role has no base URL, so the providers cannot be built | Open Settings, complete that role and save; its **Test connection** button names the missing field. Do not move the file aside: it still holds the other role's working settings |
| `404 cycle_not_found` / `422 cycle_not_ready` / `409 simulation_running` | Unknown cycle, unfinished cycle, or a run in progress | Pick a complete cycle; wait for the run to finish |
| `409 *_generation_in_progress` | The other orchestrator job (report/advisory) is running | Wait. The two jobs are serialized on purpose |
| `409 post_run_jobs_in_progress` on Run | Advisory or report still running after the last run | Wait for the report to finish (`post_run_pipeline_completed` in the server log), then Run again. The UI shows this message in an error row under the top bar, which × dismisses; on the onboarding seed step it appears above the buttons |
| `/api/health` status `degraded` | A required component is down | `components.<name>.fix` holds the fix. Neo4j stopped: "Start Neo4j (docker compose up -d neo4j, or docker start <name> for a container you created yourself)"; once it answers, the next probe applies the schema, no restart needed. If your data lives in a container you created yourself (for example `neo4j`), `docker start` it: compose would start a second, empty `alphaswarm-neo4j`. Password rejected (`credentials rejected (AuthError)`): "Set ALPHASWARM_NEO4J__PASSWORD in .env to the database's password, then restart the server". Missing alias: `ollama create alphaswarm-worker -f modelfiles/Modelfile.worker` (or the orchestrator's). Ollama down: start it with `OLLAMA_USE_MLX=1` (§1) |
| Market block empty or price-less | No resolved tickers (SEC map not cached), a yfinance deadline, or RSS fetch failures | `uv run python scripts/context_probe.py --show-block`; check `ticker_map_loaded source=sec`, `market_fetch_deadline_exceeded` and the data-source audit for `fetch_failed` |
| Graph empty during a round | Backend not streaming per-agent state, or an older backend still running | Restart the backend. Confirm `agent_states` keys in a WS frame |
| Neo4j auth error at startup | `ALPHASWARM_NEO4J__PASSWORD` unset, or it differs from the initialized volume | README §3 "Migrating". `NEO4J_AUTH` only applies when a volume is first initialized |
| `pytest` Neo4j tests all skipped | neo4j-test is not running | `scripts/neo4j_test.sh up`; add `--require-neo4j` to make a missing database fail instead of skip |
| pytest exits with code 3 ("Refusing to run Neo4j tests") | neo4j-test holds leftover cycles from a crashed session, or something else answers on 7688 | `scripts/neo4j_test.sh reset` |
| Replay or history list empty, or a finished run missing from it | The lists show only cycles whose `Cycle.status` is `complete`: a stopped run is `cancelled`, a failed one `failed` with an `error_code`, and a hard-killed one stays `running` (BACKLOG 1.15). Or the history was wiped | `MATCH (c:Cycle) RETURN c.status, count(c)`; for one cycle `MATCH (c:Cycle {cycle_id:$id}) RETURN c.status, c.error_code, c.metrics_recorded_at`. `alphaswarm report --cycle <id>` still reads a cycle that is not complete. If a checkout from before `Cycle.status` was mid-run when this version first started, the back-fill marked that cycle `failed` and it stays hidden after it finishes (`failed`, metrics set, no `error_code`): set it to `complete` by hand. Restore a wiped history from `data/backups/` |
| Cloud run: many PARSE_ERRORs or 429s | Provider rate limit | Lower `requests_per_min`, set `max_in_flight: 1`, raise `max_retries` (see §4 cloud) |
| `GovernorCrisisError` | Sustained macOS memory pressure (5 min with no successful inference) | Close memory-heavy apps. Check that `ollama ps` shows only 2 models. Lower `ALPHASWARM_GOVERNOR__BASELINE_PARALLEL` |

### CLI exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success (bare `alphaswarm` prints help and exits 0) | — |
| 1 | Runtime failure (Neo4j down, inference error, …) | Re-run with `-v` for the traceback; check that Neo4j is up (§3) and the Ollama env (§1) |
| 2 | Usage or configuration error | Fix the arguments, `.env` value or `.secrets/inference.json` named in the message |
| 130 | Interrupted with Ctrl-C | — |

Logs go to stderr, so `alphaswarm report <cycle_id> > report.txt` captures only the report output; add `2> run.log` to keep the logs.

## 7. Tests and quality gates

**Suites**
- Offline (CI `backend-unit`): `uv run pytest -q -m "not neo4j and not live_network and not ollama"`. CI adds `--cov=alphaswarm --cov-branch --cov-fail-under=85`.
- Neo4j (CI `backend-neo4j`), against the throwaway tmpfs database on 127.0.0.1:7688, never the dev database on 7687 (§3): `scripts/neo4j_test.sh up`, then `uv run pytest -q -m neo4j --require-neo4j`, then `scripts/neo4j_test.sh down`. Never stop it with a bare `docker compose --profile test down`: that also removes the dev container.
- Live (CI nightly, `.github/workflows/nightly.yml`): `uv run pytest -q --run-live -m live_network`. Cloud smoke tests also need their API keys and skip without them.
- Every test has a 60 s timeout (`pytest-timeout`, `timeout = 60` in `pyproject.toml`); every CI job has a 15-minute one.

**Markers.** `neo4j`, `live_network`, `ollama`, `slow`. Sockets are opened by these markers only (`tests/support/markers.py`): `neo4j`, `live_network` and `ollama` get sockets, async `neo4j` tests share the session event loop with the session-scoped driver, and `live_network`/`ollama` tests are skipped unless `--run-live` is given. `slow` is informational. Every module under `tests/neo4j/` sets `pytestmark = pytest.mark.neo4j`. Never enable sockets by a test's path; `enable_socket` still works as a one-off escape hatch, but prefer the markers.

**Seeded cycle and goldens.** `tests/support/seed_builder.py` writes one deterministic, fictional 100-agent cycle per session (`seeded_cycle`). Read-model and template goldens live in `tests/golden/reads/` and `tests/golden/report/` (`tests/support/golden.py` normalizes ids and timestamps). Regenerate only in a commit whose purpose explains the change: `UPDATE_GOLDEN=1 uv run pytest -q -m neo4j --require-neo4j tests/neo4j/`, then review `git diff tests/golden` line by line and say in the commit body why each file changed. The engine scenario goldens in `tests/golden/scenarios/` need no services: `UPDATE_GOLDEN=1 uv run pytest -q tests/engine/`. `UPDATE_GOLDEN` is refused when `CI=true`.

**Known bugs.** Pinned with `xfail(strict=True, reason="<item id>: …")`. The fix makes the test XPASS, which fails the run until the marker is removed in the same commit (together with any golden the fix now allows). CI runs pytest with `-rxX` and lists every XFAIL/XPASS in the job summary.

**Strict config and warnings.** `[tool.pytest.ini_options]` sets `strict_markers`, `strict_config` and `xfail_strict` as ini keys (pytest 9 ignores `--strict-*` flags that arrive through `addopts`), plus `filterwarnings = ["error"]`. An unregistered marker or an unknown ini key is an error, an xfail without `strict=False` fails the run when it passes, and any warning raised in a test fails that test. When a run goes red on a warning, fix the code that raises it. If the warning comes from a third-party library, add one targeted entry after `"error"`, `ignore:<message>:<WarningClass>:<module>`, with a comment saying why and when it can go; never a blanket `ignore` or a class-wide `ignore::<WarningClass>`. `tests/invariants/test_pytest_config.py` pins these settings and the entry format. The nightly live suite (yfinance, feedparser, httpx) runs under the same config, so a library release that starts warning turns the nightly red: apply the same rule.

**Static gates (CI `lint`).** `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run lint-imports && uv run vulture src vulture_whitelist.py --min-confidence 80`.
- Ruff runs at 120 columns (`pyproject.toml [tool.ruff]`); `ruff format` is enforced.
- mypy is strict; modules under `[[tool.mypy.overrides]]` are exempt until cleaned up, and the list only shrinks (`tests/invariants/test_mypy_overrides.py`).
- vulture fails on dead code at 80% confidence or more. `vulture_whitelist.py` lists only names an interface requires (such as `cls` on validators), each with its reason; delete dead code instead of whitelisting it.
- Hooks: `uv run pre-commit install` once per clone; it runs ruff check --fix, ruff format and import-linter (`.pre-commit-config.yaml`).
- `git config blame.ignoreRevsFile .git-blame-ignore-revs` makes local `git blame` skip the mass reformat.

**Frontend.** Node 22 (`frontend/.nvmrc`). CI runs `npm ci`, `npm audit --omit=dev --audit-level=high`, `npm run lint` (ESLint), `npx vitest run` and `npm run build` (which type-checks). Test layout, rules and the lint baseline: `frontend/TESTING.md`.
