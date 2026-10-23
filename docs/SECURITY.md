# Security

AlphaSwarm is a single-user research application that runs on the operator's own
machine. This page describes what it protects, how, where the code lives, what it does
not protect, and how to report a problem. Design rationale is in
[DECISIONS.md](DECISIONS.md) (`adr-security-2026-08`, `adr-holdings-isolation`,
`adr-advisory-pipeline`, `adr-local-first-inference`); operations are in
[RUNBOOK.md](RUNBOOK.md).

## Scope

- Supported: the latest commit on `master`, run as documented: uvicorn bound to
  `127.0.0.1:8000`, Neo4j in Docker bound to `127.0.0.1`, Ollama on `localhost:11434`.
- Not supported: exposing the API, the WebSocket, Neo4j or Ollama beyond the local
  machine, multi-user deployments, or running untrusted code as the operator.

## Threat model

| Asset | Threat | Who |
|---|---|---|
| Holdings CSV (tickers, quantities, cost basis) and advisory results | Disclosure through prompts, logs, files, HTTP responses or the live stream | A web page the operator visits; a cloud LLM provider; another local account; readers of the public git repository |
| Cloud API keys in `.secrets/inference.json` | Disclosure through logs, API responses or file permissions | Same as above |
| The operator console (simulation, settings, advisory, replay) | Cross-site requests (CSRF), cross-site WebSocket hijacking, DNS rebinding | A web page the operator visits |
| Agent behaviour | Prompt injection through RSS headlines (first order) and through peer rationales (second order) | Anyone who can get a headline indexed by a feed |
| The Neo4j database | Network access with a published default password | Anyone on the network |

The console has no login. Its protection is that it binds to loopback and answers only
loopback Host headers and allow-listed browser origins.

## Mitigations

| Threat | Mitigation | Where |
|---|---|---|
| DNS rebinding | `TrustedHostMiddleware` answers only `AppSettings.trusted_hosts` (default `localhost`, `127.0.0.1`, `[::1]`) on HTTP and the WebSocket; it is the outermost middleware | `src/alphaswarm/web/app.py`, `tests/test_trusted_host.py` |
| CSRF | One origin allow-list (`ALPHASWARM_ALLOWED_ORIGINS`) checked on every state-changing request (Origin, else Referer) | `src/alphaswarm/web/origin_guard.py`, `tests/test_web_origin_guard.py` |
| Cross-site WebSocket hijacking | The same allow-list on the `/ws/state` handshake (close code 1008); the allowed origin is never derived from the request's own Host | `src/alphaswarm/web/routes/websocket.py` |
| Holdings reaching the swarm, Neo4j or the live stream | An import-linter contract allows only the advisory code and the holdings/advisory routes to import the holdings package; a sentinel canary runs the real advisory and checks logs, Neo4j calls, frames and prompts, including the invalid-JSON failure path; the portfolio lives in `app.state.portfolio_cache`, never on the shared AppState | `pyproject.toml`, `tests/invariants/test_holdings_isolation.py`, `src/alphaswarm/web/routes/holdings.py` |
| Holdings reaching a cloud LLM | With a cloud orchestrator the advisory runs only after "Allow cloud advisory" is enabled in Settings; otherwise the POST returns 409 `cloud_advisory_disabled` and the post-run pipeline skips it while the report still runs. The prompt carries held tickers only, never quantities or cost basis | `src/alphaswarm/inference/factory.py`, `src/alphaswarm/advisory/engine.py`, `tests/test_cloud_advisory_opt_in.py` |
| Holdings in error messages | HTTP bodies name the exception class only. A validation failure, whose text echoes the model's input, is logged as its error count, locations and types, never its text or traceback, and the advisory job's own failure line never carries a traceback. Other advisory exceptions keep their traceback in the done-callback and post-run logs (see Known limitations) | `src/alphaswarm/advisory/engine.py`, `src/alphaswarm/web/routes/advisory.py`, `tests/test_advisory_error_hygiene.py` |
| Holdings in files | Advisory and report files are written atomically with mode 0600; only the newest `ALPHASWARM_ADVISORY_KEEP_LAST` advisories are kept | `src/alphaswarm/fsutil.py` |
| Holdings in the repository | The curated sector map lives in the gitignored `data/sector_map.local.json` (a fictional example ships in `examples/sector_map.example.json`); test fixtures use reserved fictional tickers; `scripts/ticker_scan.py` and `scripts/privacy_scan.py` check files and history and print counts only | `src/alphaswarm/advisory/sector_map.py`, `tests/invariants/test_fictional_fixtures.py` |
| Secrets in logs | A fail-closed structlog redactor removes holdings and credential keys and scrubs API-key shapes (`sk-…`, `nvapi-…`, `Bearer …`) from every string; stdlib logging (uvicorn, httpx, provider SDKs) goes through the same chain once logging is configured, which `./start` and `alphaswarm web` do before uvicorn starts (a direct `uvicorn` launch prints its first two startup lines in uvicorn's own format, before the app takes over uvicorn's loggers); tracebacks never include local variables, and their text is scrubbed in JSON and console output alike | `src/alphaswarm/logging.py`, `tests/test_logging_bridge.py`, `tests/invariants/test_secret_isolation.py` |
| Secrets on disk and in the API | The inference config is written owner-only (file 0600, directory 0700); `GET /api/settings` returns only whether a key is set and its last four characters | `src/alphaswarm/config.py`, `src/alphaswarm/web/routes/settings.py` |
| Prompt injection through headlines | Headlines are sanitized and fenced in the user message as untrusted data; only fixed guard text is in the system role | `src/alphaswarm/worker.py`, `src/alphaswarm/ingestion/rss_provider.py` |
| Prompt injection through peer rationales | Rationales are sanitized (no newlines, control or format characters (zero-width, bidi and invisible tag characters included), angle or square brackets; capped near 300 characters) and fenced in `<peer_observations>` in the user message behind a fixed guard | `src/alphaswarm/utils.py`, `src/alphaswarm/simulation.py`, `tests/test_peer_fence.py` |
| Neo4j exposure | No default password: the app and Compose refuse to start without `ALPHASWARM_NEO4J__PASSWORD`; ports are bound to `127.0.0.1`. The test database (`neo4j-test`, port 7688, tmpfs, Compose profile `test`) uses the throwaway credential `neo4j/alphaswarm-test-only`, which is not a secret | `docker-compose.yml`, `src/alphaswarm/config.py`, `tests/conftest.py` |
| Error responses | One error envelope; 500 responses carry a request id, never exception text or file paths | `src/alphaswarm/web/errors.py` |

## Known limitations

- **No authentication.** Any process on the machine, under any local account, can call
  the API on `127.0.0.1:8000`. Requests without an `Origin` or `Referer` header (curl,
  scripts) pass the origin guard by design; only browsers are constrained.
- **Cloud roles send data off the machine.** A role set to a cloud provider sends its
  prompts (the rumor, personas, market headlines, peer rationales) to that provider.
  After the opt-in, the advisory sends held tickers to a cloud orchestrator.
- **Prompt injection is reduced, not eliminated.** Fencing and sanitizing make injected
  text much less effective; a model can still be influenced by it.
- **Pattern-based log scrubbing.** Key-shaped strings are scrubbed by pattern; an
  unusual key format could pass.
- **Advisory exception text.** An advisory failure other than a validation error is
  logged with its traceback, message included, so it can be diagnosed. The redactor
  removes key shapes and holdings-named fields from it, not arbitrary text.
- **IPv6 host names.** Starlette's host check compares the text before the first `:`,
  so `http://[::1]:8000` is rejected; use `localhost` or `127.0.0.1` (the server binds
  `127.0.0.1` anyway).
- **Ollama is unauthenticated.** It listens on `localhost:11434` with its own defaults.
- **Earlier credentials.** Older commits published a default Neo4j password and
  all-interface ports; both were removed in August 2026 and the password was rotated.
- **History.** Before October 2026 some public commits contained the owner's real
  positions (planning documents and two test files). They were replaced with fictional
  values, but those older commits still contain them; the history was deliberately not
  rewritten. Older commits also name the owner's tickers (without quantities) in many
  files, not only the curated map that `src/alphaswarm/advisory/sector_map.py` held and
  its test: test fixtures, docstrings and comments across `src/`, `tests/` and
  `frontend/src/`, and the retired planning documents. The current tree uses reserved
  fictional tickers instead (October 2026); the older commits still contain the real ones.

## Reporting a vulnerability

Report privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**. Please do not open a public issue for a security problem.
If the **Report a vulnerability** button is not shown, open an issue that asks for a
private contact and leave out every detail of the problem.
This is a personal project maintained by one person; expect a reply within a week.

## Security reviews

Claude Security scans on 2026-08-01 and 2026-08-02 found the issues fixed in commits
`53e5954`, `72d55a9`, `45c7827`, `1e7a8ee`, `e353716` and `820b8fe` (see
`adr-security-2026-08` in [DECISIONS.md](DECISIONS.md)). The October 2026 hardening is
recorded in the same file: TrustedHost, the one origin list, peer-rationale fencing,
the logging bridge and the run context under `adr-security-2026-08`; the cloud-advisory
opt-in, ticker-only advisory prompts, advisory failure logging and owner-only advisory
files under `adr-advisory-pipeline`; the API-key scrub, the validation-error rule and
the sector-map move under `adr-holdings-isolation`. The scan reports are kept
privately and are not published (gitignored, never committed).
