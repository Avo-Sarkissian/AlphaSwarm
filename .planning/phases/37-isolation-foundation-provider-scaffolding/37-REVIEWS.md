---
phase: 37
reviewers: [gemini, codex]
reviewed_at: 2026-04-18T00:00:00Z
plans_reviewed:
  - 37-01-PLAN.md
  - 37-02-PLAN.md
  - 37-03-PLAN.md
  - 37-04-PLAN.md
---

# Cross-AI Plan Review — Phase 37: Isolation Foundation & Provider Scaffolding

## Gemini Review

This review covers the four implementation plans for **Phase 37: Isolation Foundation & Provider Scaffolding**.

### 1. Summary
The implementation strategy for Phase 37 is exceptionally robust, utilizing a defense-in-depth approach to ensure information isolation. By combining static enforcement (`import-linter`), runtime validation (`Pydantic extra="forbid"`), network-level gating (`pytest-socket`), and automated verification (the "Four-Surface Canary"), the plans effectively mitigate the risk of user holdings leaking into the AI swarm. The use of Hypothesis for PII redaction fuzzing and the "fail-closed" logging policy demonstrates a high degree of engineering maturity.

### Strengths
- **Defense-in-Depth:** The plan doesn't rely on a single mechanism; it layers linting, typing, logging, and network gates to catch leaks at different stages of the lifecycle.
- **The Four-Surface Canary:** Validating that sentinels are absent from logs, Neo4j, WebSockets, and prompts is a masterclass in automated safety verification. This catches "accidental" pass-throughs that static analysis might miss.
- **Fuzzing PII Redaction:** Using `hypothesis` to ensure the redaction logic handles edge cases (like nested dicts or unusual string patterns) is significantly more reliable than standard unit tests.
- **Strict Pydantic Config:** Using `extra="forbid"` and `frozen=True` on the ingestion types ensures that downstream developers cannot "hack" holdings into context packets without changing the core schema.
- **Network Gating:** Blocking loopback by default (`--disable-socket`) is a strict but correct move to prevent unintended side-channels during local development and testing.

### Concerns
- **Async/Sync Ambiguity in Protocols (37-02) — MEDIUM:** The plan defines the `MarketDataProvider` Protocol but doesn't explicitly verify methods are `async def`. If implemented as sync, they will block the event loop during Phase 38.
- **Regex Backstop Performance (37-03) — LOW:** Global PII redaction with regex for every log event can introduce latency in a "chatty" multi-agent simulation. Regex should be compiled once and optimized.
- **ImportLinter programmatic invocation (37-04) — LOW:** Invoking `lint-imports` inside a `pytest` file — ensure the environment has the `import-linter` binary available in the path where `pytest` runs.
- **Decimal Handling (37-04) — LOW:** The canary uses `Decimal("999999.99")`. Ensure structlog/JSON serializers handle `Decimal` objects, or the canary might fail due to serialization errors rather than isolation leaks.

### Suggestions
- **Protocol Asyncification:** Explicitly define `MarketDataProvider` and `NewsProvider` methods as `async def` (they should already be, but verify in acceptance criteria).
- **SHA256 Truncation Length:** Consider 16 chars instead of 8 for account hashes if collision avoidance matters at scale (8 chars = 32 bits entropy).
- **Case-Insensitive Redaction Keys:** In `pii_redaction_processor`, ensure key matching is case-insensitive (`Holdings`, `HOLDINGS`, `costBasis`) to prevent naming-convention bypasses.
- **Positive Control Clarity:** Ensure positive-control canary tests are clearly labeled so a capture machinery failure isn't mistaken for a clean isolation run.
- **Staleness Enum:** Use `Literal["fresh", "stale", "fetch_failed"]` or a `StrEnum` for `staleness` instead of unconstrained string.

### Risk Assessment
**LOW.** Plans are highly prescriptive and align with the Option A architecture. Primary risks are minor implementation details rather than architectural flaws.

---

## Codex Review

### Summary

The four plans are directionally strong and mostly aligned with Phase 37's purpose: define isolation boundaries before enrichment, holdings, and advisory code exist. The sequencing is sensible: foundational types first, provider protocols and test/network controls next, then import boundaries and canary scaffolding. The main risks are around "frozen" being interpreted too shallowly, import-linter scope becoming brittle or incomplete, pytest-socket interfering with local infrastructure tests, and the canary plan overreaching before the simulation/advisory join points actually exist.

### Plan 37-01 — Frozen Types & Dev Dependencies

**Strengths:**
- Correctly starts with type boundaries before ingestion or advisory behavior exists.
- Uses stdlib frozen dataclasses for holdings and Pydantic v2 frozen models for swarm-side context.
- `extra="forbid"` on swarm-side types directly supports the "no holdings fields" invariant.
- Adding `import-linter`, `pytest-socket`, and `hypothesis` early is appropriate because later phases inherit these constraints.
- `sha256_first8` is small, deterministic, and reusable by redaction logic.

**Concerns:**
- **HIGH:** `frozen=True` is shallow. A frozen dataclass containing `list[Holding]` or a Pydantic model containing `dict`/`list` fields can still have nested mutable values mutated in place.
- **HIGH:** Financial fields should be `Decimal`, not `float`, for `qty`, `cost_basis`, `price`, and possibly fundamentals values.
- **MEDIUM:** `PortfolioSnapshot(holdings, ...)` should use `tuple[Holding, ...]`, not `list[Holding]`, to preserve immutability.
- **MEDIUM:** `ContextPacket.entities` and `NewsSlice.headlines` should be tuples. `MarketSlice.fundamentals` needs a clear immutable or read-only strategy.
- **MEDIUM:** `frozen=True` plus `extra="forbid"` doesn't prove absence of holdings semantics unless tests explicitly check field names and serialized output.
- **LOW:** `account_number_hash` in holdings types may interact awkwardly with redaction rules that key off `account_*` fields — avoid double-hashing already-tokenized identifiers.

**Risk Assessment:** MEDIUM — conceptually correct, but immutability guarantee is weaker than it appears without addressing nested mutability.

### Plan 37-02 — Provider Protocols & Fakes

**Strengths:**
- Good separation: protocols and fakes only, no real network providers in Phase 37.
- Batch-first signatures align with D-18.
- Returning `staleness="fetch_failed"` instead of raising aligns with D-19.
- Avoiding `@runtime_checkable` is reasonable.
- In-memory fakes are appropriate for canary and isolation tests.

**Concerns:**
- **HIGH:** `MarketDataProvider` with three methods (`get_prices`, `get_fundamentals`, `get_volume`) may create partial/inconsistent `MarketSlice` objects since each method only knows one data subset.
- **MEDIUM:** A single `get_market_slices(tickers)` method may better match the batch-first locked decision (D-17).
- **MEDIUM:** "Providers never raise" should cover malformed fixture data, empty input, duplicate tickers, and unexpected internal errors — not just unknown keys.
- **MEDIUM:** Provider methods must be explicitly `async def` in the protocol (project is asyncio-only).
- **LOW:** `list[str]` allows duplicate tickers — expected behavior for duplicates should be defined.
- **LOW:** `staleness` should be `Literal["fresh", "stale", "fetch_failed"]`, not unconstrained string.

**Suggestions:**
- Add tests for empty input, duplicate tickers, fetch_failed for every unknown key, awaitable methods, and exceptions-as-failed-slices.
- Define `StalenessState = Literal["fresh", "stale", "fetch_failed"]` type alias and use it consistently.

**Risk Assessment:** MEDIUM — provider abstraction is useful but market protocol shape may cause awkward downstream contracts.

### Plan 37-03 — PII Redaction + Network Gate

**Strengths:**
- Installing redaction before holdings code exists is exactly the right timing.
- Key-first redaction with regex backstop matches the locked decisions.
- `--disable-socket` globally is a strong default.
- Loopback tripwire test is valuable (localhost often sneaks through).
- Positive-control tests avoid false confidence from broken capture fixtures.
- Hypothesis fuzzing is appropriate for a redaction processor.

**Concerns:**
- **HIGH:** "Fail-closed: raise `DropEvent` + emit `redaction_failed` marker" is tricky. Once `DropEvent` is raised, the event is dropped. Emitting a marker from inside the failing processor risks recursion through the same structlog pipeline.
- **HIGH:** Redaction must recurse through nested dicts/lists/tuples/dataclasses/Pydantic models. A top-level key-only implementation misses shapes like `{"event": "x", "payload": {"portfolio": ...}}`.
- **HIGH:** Sensitive key matching must handle variants: `costBasis`, `cost_basis_usd`, `accountNumber`, `acct_id`, `positions_by_account`.
- **MEDIUM:** Redacting `qty` and `shares` globally may remove non-sensitive operational fields and hurt debugging.
- **MEDIUM:** Regex backstop for currency can over-redact ordinary market prices.
- **MEDIUM:** `account_number_hash` should be treated as already safe or normalized to avoid `acct:{hash(hash)}`.
- **MEDIUM:** `pytest-socket` can break tests using FastAPI `TestClient`, Uvicorn, Neo4j fixtures, or local HTTP mocks.
- **LOW:** Hypothesis `deadline=1000` may be flaky on loaded machines with deeply nested structures.

**Suggestions:**
- Implement redaction as a pure recursive sanitizer with cycle/depth protection.
- Emit `redaction_failed` through a minimal fallback path that cannot recurse through the same failing processor.
- Define key normalization rules: lowercase, remove separators, support snake_case and camelCase.
- Keep regex backstop narrow and tested; avoid accidentally redacting every market price.
- Confirm `addopts` appends to existing pytest options rather than replacing them.

**Risk Assessment:** MEDIUM-HIGH — plan is right but implementation details can easily create blind spots.

### Plan 37-04 — importlinter Contract + Canary Invariants

**Strengths:**
- Import boundary enforcement is essential for the core invariant.
- Forbidden contract is simpler than layered enforcement.
- Testing with a synthetic violation is a good CI confidence check.
- Four-surface canary directly encodes the most important isolation invariant.
- Integration auto-marker is a practical escape hatch for global socket blocking.

**Concerns:**
- **HIGH:** Listing "all top-level modules" manually in `source_modules` is brittle — new modules added later may be accidentally omitted.
- **HIGH:** D-04 says only `alphaswarm.advisory` and `alphaswarm.web.routes.holdings` may import `alphaswarm.holdings`. Source list must cover every other package, including future packages.
- **HIGH:** `test_importlinter_contract.py` using a synthetic violating module may be hard to make reliable if import-linter analyzes installed packages or config from disk differently under pytest.
- **MEDIUM:** The canary "runs minimal simulation body with fakes" — Phase 37 may not yet have stable join points for Neo4j writes, WebSocket frames, and worker prompts. Could be over-engineered or too mocked to be meaningful.
- **MEDIUM:** Sentinel absence checks can produce false positives if values are transformed, rounded, serialized as numbers, lowercased, or split across prompt fragments.
- **LOW:** `.pre-commit-config.yaml` is useful locally, but CI must run `lint-imports` directly.
- **LOW:** Neo4j and WebSocket fake surfaces should be pure in-memory and socket-free or they may conflict with the global network gate.

**Suggestions:**
- Add a test that enumerates `alphaswarm` top-level packages and asserts each is either forbidden-source-covered or explicitly allowlisted.
- Run the real `lint-imports` command in a subprocess with a temporary violating module on `PYTHONPATH`, then assert failure.
- Keep Phase 37 canary honest: if no real join point exists, mark four-surface tests as scaffolded with explicit activation points at the advisory phase.
- Search for multiple representations of sentinels: raw strings, `Decimal` string forms, JSON-serialized forms, account hash forms.

**Risk Assessment:** MEDIUM-HIGH — targets the right controls, but import-linter coverage and canary realism are the main risks.

---

## Consensus Summary

Phase 37 reviewed by **2 AI systems** (Gemini, Codex). Both reviewers agree the phase structure is sound and sequenced correctly. There is strong consensus on the defense-in-depth approach and the value of installing guardrails before sensitive data flows exist.

### Agreed Strengths

- Defense-in-depth approach (import gates + type enforcement + network blocking + PII redaction + canary) is the right architecture for this invariant
- Four-surface canary (logs, Neo4j, WebSocket, prompts) is a high-value safety invariant
- Hypothesis fuzzing for PII redaction is more reliable than unit tests alone
- Installing guardrails before holdings code exists is exactly the right timing
- Positive-control tests prevent false-assurance from broken capture fixtures

### Agreed Concerns (Priority Order)

1. **[HIGH] Shallow immutability** — `frozen=True` doesn't prevent nested mutable fields (e.g., `list[Holding]` inside a frozen dataclass). Use `tuple[Holding, ...]`, `tuple[str, ...]` for collection fields throughout.
2. **[HIGH] Redaction must be recursive** — key-only top-level redaction misses nested payloads like `{"event": "x", "payload": {"portfolio": [...]}}`. Implement recursive sanitizer with cycle/depth protection.
3. **[HIGH] importlinter source_modules is brittle** — manual enumeration of all top-level modules will drift as new modules are added. Add a coverage test that enumerates actual packages and asserts each is either listed or explicitly allowlisted.
4. **[HIGH] Fail-closed recursion risk** — emitting `redaction_failed` marker from inside a failing `DropEvent` processor may recurse through the same pipeline. Use a fallback path that bypasses the PII processor.
5. **[MEDIUM] Provider async contract must be explicit** — Protocol methods must be `async def` to preserve project asyncio-only constraint; acceptance criteria should grep for `async def get_`.
6. **[MEDIUM] Case-insensitive/variant key matching** — redaction misses `costBasis`, `HOLDINGS`, `acct_id`, `positions_by_account` naming variants.
7. **[MEDIUM] `staleness` should be a typed literal** — use `Literal["fresh", "stale", "fetch_failed"]` or `StrEnum`, not unconstrained string.
8. **[MEDIUM] Financial precision** — use `Decimal` for financial quantities in `MarketSlice.price`, `MarketSlice.volume` (where applicable), and any fundamentals values.

### Divergent Views

- **Provider method granularity (MEDIUM):** Codex recommends collapsing three `MarketDataProvider` methods into one `get_market_slices`; Gemini accepts the three-method shape. The three-method design aligns with D-17/D-18 locked decisions; Codex's concern is about partial/inconsistent `MarketSlice` objects. Worth considering whether a single combined method better fits the batch-first pattern.
- **Overall risk level:** Gemini assessed LOW risk (well-structured, minor implementation details); Codex assessed MEDIUM risk (implementation details around immutability and redaction depth are meaningful gaps). The truth is probably MEDIUM for execution — the architecture is sound but the details matter.
- **SHA256 truncation length:** Gemini flagged 8 chars as potentially insufficient for collision resistance; this is low risk for a local simulation but worth noting.
