---
phase: 30
slug: websocket-state-stream
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-13
---

# Phase 30 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser → WebSocket | Unauthenticated local-dev-only connection to /ws/state | Simulation state JSON (metrics only, no PII, no auth tokens) |
| Broadcaster → ConnectionManager | Internal asyncio task writes to per-client queues | StateSnapshot JSON serialized via snapshot_to_json |
| lifespan → broadcaster | asyncio.Task created/cancelled inside FastAPI lifespan | None — task lifecycle management only |

*Per D-10: local dev only. CLI defaults to 127.0.0.1 — endpoint not reachable from network.*

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-30-01 | DoS | WebSocket receive loop | accept | receive_text() rate-limited by TCP; local-dev only — no application-layer mitigation needed | closed |
| T-30-02 | DoS | ConnectionManager | mitigate | Bounded queue (100 msgs) + drop-oldest prevents unbounded memory growth per idle client | closed |
| T-30-03 | Information Disclosure | broadcaster._broadcast_loop | mitigate | `except Exception` catches serialization errors; logged with throttle counter; no traceback sent to client | closed |
| T-30-04 | DoS | broadcaster._broadcast_loop | mitigate | `except Exception` (not BaseException) — CancelledError propagates through asyncio.sleep(0.2) unimpeded; zombie task impossible | closed |
| T-30-05 | Data Integrity | snapshot_to_json | mitigate | Explicit `d["rationale_entries"] = drain_rationales()` override after `asdict(snap)` prevents silent loss; covered by test_snapshot_to_json | closed |
| T-30-06 | Data Integrity | broadcaster ↔ ws endpoint | mitigate | Object identity: same `connection_manager` variable passed to start_broadcaster and stored on app.state; verified by test_ws_state_same_connection_manager | closed |
| T-30-07 | DoS | broadcaster log output | mitigate | consecutive_failures counter throttles error logging to once per 10 failures; prevents log flood under repeated Ollama/Neo4j failures | closed |
| T-30-08 | Availability | lifespan teardown | mitigate | broadcaster_task.cancel() called before graph_manager.close() — correct ordering prevents use-after-close on state_store | closed |
| T-30-09 | Spoofing | ws_router registration | mitigate | ws_router registered without prefix; /ws/state does not collide with /api/* namespace | closed |
| T-30-10 | DoS | lifespan singleton | accept | asynccontextmanager guarantees single lifespan execution per app instance; multiple broadcaster tasks structurally impossible | closed |
| T-30-11 | Data Integrity | production wiring | mitigate | test_create_app_ws_route_registered exercises real create_app() path; production silent-breakage prevented by CI test | closed |
| T-30-12 | Exposure | WebSocket binding | mitigate | CLI `--host` defaults to 127.0.0.1 (cli.py:881); /ws/state not reachable from external network interfaces in default config | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-30-01 | T-30-01 | Local-dev only per D-10; TCP provides natural backpressure; no auth layer planned for this phase | developer | 2026-04-13 |
| AR-30-10 | T-30-10 | Structural guarantee from asynccontextmanager; no additional mitigation needed | developer | 2026-04-13 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-13 | 12 | 12 | 0 | gsd-secure-phase (static analysis — threats_open: 0 at audit time) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-13
