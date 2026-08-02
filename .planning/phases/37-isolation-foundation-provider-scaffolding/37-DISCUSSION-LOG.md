# Phase 37: Isolation Foundation & Provider Scaffolding - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 37-isolation-foundation-provider-scaffolding
**Areas discussed:** importlinter contract shape, PII redaction strategy, pytest-socket scope, canary test design, provider Protocol granularity

---

## Area 1: importlinter contract shape

### Q1.1 — Contract type

| Option | Description | Selected |
|--------|-------------|----------|
| Forbidden modules | `type = "forbidden"`, explicit source + forbidden lists, matches research ADR sketch | ✓ |
| Layered architecture | Full layer stack (`advisory > holdings > ingestion > swarm`); catches future leaks but all modules must be classified | |
| Both | Forbidden for hard rule + lightweight layered for `ingestion ↛ simulation.worker` direction | |

**User's choice:** Forbidden modules (recommended)
**Notes:** Minimum-viable isolation with low maintenance; matches research spec verbatim.

### Q1.2 — Enforcement points

| Option | Description | Selected |
|--------|-------------|----------|
| CI only | `uv run lint-imports` in CI only | |
| CI + pre-commit hook | Local fast feedback (~1s) + authoritative CI gate | ✓ |
| CI + pre-commit + `just lint` target | All three bundled with ruff+mypy | |

**User's choice:** CI + pre-commit hook (recommended)
**Notes:** Catches 95% locally without slowing workflow; CI remains authoritative.

### Q1.3 — Violation intent test

| Option | Description | Selected |
|--------|-------------|----------|
| One-shot manual test | Branch, run lint-imports, record in PLAN, revert | |
| Permanent unit test | `tests/invariants/test_importlinter_contract.py` invokes lint-imports programmatically on synthetic violator | ✓ |
| Git-tagged violation branch | Kept as historical evidence, CI doesn't run it | |

**User's choice:** Permanent unit test (recommended)
**Notes:** Self-documenting, runs on every CI, guards against anyone loosening the contract later.

### Q1.4 — Scope of forbidden importers

| Option | Description | Selected |
|--------|-------------|----------|
| Spec scope only | Forbid only from simulation/worker/ingestion/seed/parsing (5 modules) | |
| Spec + web routes | Add web except `web.routes.holdings` | |
| Whitelist-only (inverse) | Forbid from everything except `advisory` + `web.routes.holdings` | ✓ |

**User's choice:** Whitelist-only (recommended)
**Notes:** Strongest posture; matches Option A invariant ("HoldingsStore has exactly one consumer: AdvisoryPipeline"). Whitelist makes the boundary explicit and future-proof.

---

## Area 2: PII redaction strategy

### Q2.1 — Detection approach

| Option | Description | Selected |
|--------|-------------|----------|
| Key-based only | Allowlist of sensitive key names; fast, deterministic, misses nested data | |
| Value-pattern only | Regex for SSN/currency/hashes; catches unknown leaks, false-positive prone | |
| Both, key-first | Key matcher primary, value regex backstop on remaining strings | ✓ |

**User's choice:** Both, key-first (recommended)
**Notes:** Defense-in-depth. Key match is auditable contract; value pattern catches the "interpolated into a message string" edge case.

### Q2.2 — Redaction marker

| Option | Description | Selected |
|--------|-------------|----------|
| `"[REDACTED]"` string | Visually obvious, unambiguous | |
| SHA256 hash prefix | Correlatable across log lines, harder to scan | |
| Drop the key entirely | Invisible, no leak surface, debug-hostile | |
| Mixed | `account_*` hashed (correlation), rest `[REDACTED]` | ✓ |

**User's choice:** Mixed (recommended)
**Notes:** Account IDs need correlation for broker-adapter debugging (HOLD-04 SHA256s accounts anyway); other fields don't benefit from correlation.

### Q2.3 — Failure mode

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-open | Log original event with `redaction_failed=true` flag | |
| Fail-closed | Drop event, emit single `redaction_failed` marker with no user data | ✓ |
| Fail-hard | Raise, crashing the caller | |

**User's choice:** Fail-closed (recommended)
**Notes:** Isolation invariant demands safe default. Fail-open defeats the purpose; fail-hard takes down simulations over log bugs. Single marker event is sufficient signal.

### Q2.4 — Processor test

| Option | Description | Selected |
|--------|-------------|----------|
| Hypothesis-based fuzz | Random dicts with mixed sensitive/safe keys | |
| Tabular test | 20-30 hand-crafted scenarios (nested dicts, lists, f-strings) | |
| Both | Hypothesis for coverage + tabular for regression lock-in | ✓ |

**User's choice:** Both (recommended)
**Notes:** Hypothesis catches unknown-unknowns; tabular pins known-bad patterns from Phase 41 leak vectors.

---

## Area 3: pytest-socket scope

### Q3.1 — Default policy

| Option | Description | Selected |
|--------|-------------|----------|
| Block all outbound globally | `--disable-socket` in pyproject; opt-in via marker | ✓ |
| Block only in CI | `CI=true` env check in conftest.py | |
| Mixed per-directory | `tests/integration/` auto-enables, others block | |

**User's choice:** Block all outbound globally (recommended)
**Notes:** Matches SC #4 verbatim; no env-conditional behavior; integration tests stay explicit.

### Q3.2 — Loopback allowance

| Option | Description | Selected |
|--------|-------------|----------|
| Always block loopback too | Strict; Neo4j + Ollama integration tests need marker | ✓ |
| Always allow loopback | `--allow-hosts=127.0.0.1,localhost,::1`; leak risk via misconfigured local proxy | |
| Allow only in `tests/integration/` | Scoped allowance | |

**User's choice:** Always block loopback too (recommended)
**Notes:** Blanket policy is easier to reason about; marker overhead is one line per integration test.

### Q3.3 — Unix socket handling

| Option | Description | Selected |
|--------|-------------|----------|
| Block Unix sockets too | pytest-socket default; leave as-is | ✓ |
| Allow Unix sockets unconditionally | `--allow-unix-socket` | |
| Per-test marker | Block default, enable on demand | |

**User's choice:** Block Unix sockets (recommended)
**Notes:** No current dependency uses them (Neo4j bolt://, Ollama HTTP). Revisit if real need emerges.

### Q3.4 — Integration test marker convention

| Option | Description | Selected |
|--------|-------------|----------|
| Single marker per test | `@pytest.mark.enable_socket` everywhere needed | |
| Directory-wide marker | `conftest.py` in `tests/integration/` auto-applies | |
| Both | Directory-wide + explicit one-offs elsewhere | ✓ |

**User's choice:** Both (recommended)
**Notes:** `tests/integration/` is conceptually "online" — auto-apply avoids boilerplate; explicit marker for exceptions keeps default strict.

---

## Area 4: Canary test design

### Q4.1 — Sentinel value shape

| Option | Description | Selected |
|--------|-------------|----------|
| String markers (ASCII) | `SNTL_CANARY_TICKER`, `999999.99`, `77.7777`, `SNTL_CANARY_ACCT_000` | ✓ |
| Unicode zero-width tag | `\u200b` + UUID; invisible but greppable | |
| UUID-based | Regenerated per run | |

**User's choice:** ASCII string markers (recommended)
**Notes:** Greppable across logs/prompts/Neo4j/WS without tooling; Phase 41 activation reuses the same sentinel.

### Q4.2 — Phase 37 assertion (trivially passing)

| Option | Description | Selected |
|--------|-------------|----------|
| Type round-trip only | Construct snapshot + `str(snapshot)`; pure type test | |
| Minimal simulation + invariant check | Real sentinel snapshot run through empty sim; asserts sentinels absent from all surfaces | ✓ |
| Existence assertion | Assert `AdvisoryPipeline` does not yet exist (skip/import error) | |

**User's choice:** Minimal simulation + invariant check (recommended)
**Notes:** Establishes the invariant machinery day-one; Phase 41 only needs to wire the join point. At Phase 37 there's no holdings code path, so it trivially passes — but it's a real test.

### Q4.3 — Leak detection surface

| Option | Description | Selected |
|--------|-------------|----------|
| Logs only | structlog capture + grep | |
| Logs + Neo4j | Add post-sim node/relationship property scan | |
| Logs + Neo4j + WebSocket frames | Add broadcaster intercept | |
| All of above + rendered prompts | Hook worker prompt builder | ✓ |

**User's choice:** All four surfaces (recommended)
**Notes:** Matches PROJECT.md invariant verbatim; building all four detection points at Phase 37 makes Phase 41's activation a one-line change.

### Q4.4 — Test location / marker

| Option | Description | Selected |
|--------|-------------|----------|
| `tests/test_holdings_isolation.py` | Top-level; runs on every pytest | |
| `tests/invariants/test_holdings_isolation.py` | New invariants/ subdir | ✓ |
| `tests/integration/test_holdings_isolation.py` | Lives with integration tests | |

**User's choice:** `tests/invariants/` (recommended)
**Notes:** Matches research ADR sketch path; establishes new directory convention for future invariant tests. Marked `enable_socket` since surfaces touch Neo4j + WebSocket.

---

## Area 5: Provider Protocol granularity

### Q5.1 — Protocol split

| Option | Description | Selected |
|--------|-------------|----------|
| Two Protocols total | `MarketDataProvider` + `NewsProvider` | ✓ |
| Five Protocols | Split by query type (PriceProvider, FundamentalsProvider, etc.) | |
| Two + capability flags | `supports = {...}` class attribute | |

**User's choice:** Two Protocols (recommended)
**Notes:** Matches ISOL-05 verbatim and research SUMMARY; finer splits add ceremony without mock-ergonomic benefit for our case.

### Q5.2 — Method signatures

| Option | Description | Selected |
|--------|-------------|----------|
| Per-ticker | `get_price(ticker) -> PriceQuote` | |
| Batch-first | `get_prices(tickers: list[str]) -> dict[str, PriceQuote]` | ✓ |
| Both | Single + batch methods | |

**User's choice:** Batch-first (recommended)
**Notes:** Aligns with `yf.download()` bulk pattern; enforces right calling shape for Phase 38's 100-ticker load.

### Q5.3 — Error / staleness expression

| Option | Description | Selected |
|--------|-------------|----------|
| `MarketSlice \| None` | `None` means fetch failed | |
| Always return MarketSlice | Errors encoded (`data=None, staleness="fetch_failed"`) | ✓ |
| Raise on failure | Typed exception hierarchy | |

**User's choice:** Always return MarketSlice with encoded errors (recommended)
**Notes:** Codifies Phase 38 SC #1 verbatim at the Protocol level; trivially conformant implementations; no try/except in 100-ticker aggregation loop.

### Q5.4 — Phase 37 deliverable depth

| Option | Description | Selected |
|--------|-------------|----------|
| Protocols only | `Protocol` classes + docstrings | |
| Protocols + Fake providers | Add `FakeMarketDataProvider` + `FakeNewsProvider` for test use | ✓ |
| Protocols + Fakes + `_NotImplementedYet` sentinel | Default registered provider raises until Phase 38 | |

**User's choice:** Protocols + Fake providers (recommended)
**Notes:** Fakes are test infrastructure, not implementations. ~30 lines; unblocks Phase 38 test-first approach and enables Phase 37 canary test (Q4.3) to exercise the full provider → ContextPacket → prompt path without network.

---

## Claude's Discretion

Captured in CONTEXT.md `<decisions>` section under "Claude's Discretion":
- importlinter TOML layout specifics
- SHA256 account-hash function placement (`alphaswarm/security/hashing.py` vs `alphaswarm/holdings/redaction.py`)
- Hypothesis strategy shrinking/example-size tuning
- `tests/invariants/conftest.py` fixture shape
- Fake provider response payload shape beyond "sentinel-friendly"

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section:
- Log-grep CI gate (cruder grep-based belt-and-suspenders beyond importlinter)
- Layered importlinter contract (revisit if new top-level modules accumulate)
- `_NotImplementedYetProvider` sentinel (explicit "turn on in Phase 38" guard)
- Runtime schema assertion for ContextPacket beyond pydantic `extra="forbid"`
