---
phase: 40
reviewers: [gemini, codex]
reviewed_at: 2026-04-19T00:00:00Z
plans_reviewed: [40-01-PLAN.md, 40-02-PLAN.md, 40-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 40

## Gemini Review

# Phase 40: Simulation Context Wiring - Plan Review

This review covers the three implementation plans designed to wire grounded market data and news headlines into the AlphaSwarm simulation pipeline.

---

### 1. Summary
The plans provide a comprehensive, TDD-driven roadmap to ground the 100-agent swarm in real-world context. The strategy is divided into clear logical waves: skeleton plumbing (Plan 01), core assembly and formatting logic (Plan 02), and top-level surface wiring (Plan 03). The plans demonstrate high technical maturity by addressing the "fetch_failed" never-raise contract, ensuring financial precision via Decimal handling, and maintaining backward compatibility for rumor-only simulations.

### 2. Strengths
- **Architectural Alignment:** The decision to mirror the existing `peer_context` plumbing pattern (Plan 01) minimizes cognitive overhead and leverages a proven mechanism.
- **API Normalization:** Plan 02 correctly identifies and fixes the discrepancy between the protocol methods (`get_prices`) and the initial user request (`fetch_batch`), preventing a runtime `AttributeError`.
- **Financial Integrity:** The strict adherence to `Decimal` string representation and the "never cast to float" rule in the formatter (Plan 02) prevents floating-point precision bugs in agent prompts.
- **Defensive Design:** The `ISOL-04` canary test (Plan 02 Task 1) is a sophisticated safeguard against "redaction drift," ensuring that market data doesn't get accidentally scrubbed by the PII processor.
- **Testing Depth:** The inclusion of an end-to-end integration test (Plan 03 Task 2) using `Fake` providers ensures the entire chain — from entity extraction to prompt injection — is validated in a single event loop.

### 3. Concerns
- **[LOW] Positional Parameter Shift:** Plan 01 Task 3 inserts `market_context` as a positional parameter in `_safe_agent_inference`. While the plan updates the internal `dispatch_wave` call site, any third-party or future internal use of this private helper would be broken. *Mitigation: The helper is private (`_`) and its only consumer is updated.*
- **[LOW] Regex Duplication:** Plan 02 Task 2 lifts the `_TICKER_RE` into `simulation.py`. While effective, it duplicates logic from `rss_provider.py`. *Mitigation: Re-applying the filter at the orchestrator layer is a valid defense-in-depth measure.*
- **[LOW] Formatter Budget Greedy-Fill:** The greedy-fill strategy stops at the first entity that would overflow. In a very large rumor with many entities, this might exclude high-sentiment entities at the end of the list. *Mitigation: Given the 4000-char budget and typical entity counts (3-5), this is an extreme edge case.*

### 4. Suggestions
- In `context_formatter.py`, import `MarketSlice` and `NewsSlice` inside `if TYPE_CHECKING:` block for IDE navigation clarity.
- In the `context_packet_assembled` log (Plan 02 Task 2), consider adding a `total_headlines` count to help debug headline cap effectiveness in production logs.

### 5. Risk Assessment: **LOW**
The implementation is additive, does not break existing signatures, providers are contractually guaranteed not to raise, and TDD in Wave 1 catches plumbing errors early. **Verdict: PROCEED.**

---

## Codex Review

## Overall Assessment

The three-plan split is strong: Plan 01 isolates prompt plumbing, Plan 02 adds pure formatting and orchestration assembly, and Plan 03 wires user-facing entry points. The sequence is logical and mostly closes SIM-04/INGEST-03. The main risks are not architectural, but correctness gaps around entity-to-ticker resolution, test feasibility, and a mismatch between some claimed end-to-end coverage and what the proposed tests actually exercise.

### Plan 01

**Summary:** Plan 01 is well-scoped and appropriately narrow: it threads `market_context` through the Round 1 inference path without provider/formatter concerns. The design mirrors the existing `peer_context` path cleanly and preserves the Round 2/3 boundary.

**Strengths:**
- Clean separation of concerns: only signature/plumbing work, no provider or formatting logic.
- Correct message order: persona system prompt, market system context, peer context, user.
- Explicitly preserves D-06 by keeping `_dispatch_round` untouched.
- TDD structure is concrete and traceable.

**Concerns:**
- **[HIGH]** Existing dispatcher tests likely need updates. Current mock `infer()` functions in `tests/test_batch_dispatcher.py` accept only `user_message` and `peer_context`; once `_safe_agent_inference` passes `market_context=...`, those mocks can raise `TypeError`.
- **[MEDIUM]** `_safe_agent_inference` adds another positional argument — slightly brittle; keyword forwarding would be clearer.
- **[LOW]** The RED-step expectation is overly specific about which layer each test fails at.

**Suggestions:**
- Update all existing dispatcher mock `infer()` helpers to accept `market_context: str | None = None` or `**kwargs`.
- Prefer calling `_safe_agent_inference(..., market_context=market_context, ...)` with keyword arg.
- Add assertion that existing `peer_contexts` behavior still works when `market_context` is omitted.

**Risk: LOW to MEDIUM** — production change is simple but mock-heavy dispatcher tests likely need updates.

---

### Plan 02

**Summary:** Plan 02 has the right core shape: a pure formatter plus `run_simulation` assembly. The biggest product risk is that entities from orchestrator LLM output may be company names (e.g., `NVIDIA`) not ticker symbols (`NVDA`), so market prices may silently disappear for many real rumors.

**Strengths:**
- Pure `format_market_context()` module is a good design choice and easy to test.
- Correct protocol method names: `get_prices()` and `get_headlines()`.
- `asyncio.gather()` for parallel provider calls.
- Formatter skips `fetch_failed` slices, returns `None` for empty output.
- Budget cap and headline cap are practical context-window protections.

**Concerns:**
- **[HIGH]** Entity-to-ticker handling is under-specified. `SeedEntity.name` has no ticker field. `_TICKER_RE` only passes symbols like `NVDA`; real rumors extract `NVIDIA`, so market slices may silently be empty. Tests may be green while the feature delivers no prices in production.
- **[HIGH]** The proposed `run_simulation` tests patch `run_round1`, but `run_simulation` continues into Round 2/3 work unless downstream dependencies are consistently mocked.
- **[MEDIUM]** The ISOL-04 canary only proves field names aren't redaction literals — it doesn't prove sensitive content inside headlines is scrubbed.
- **[MEDIUM]** `context_assembly_skipped` warning fires for every default `run_simulation()` call without providers — adds noise in existing tests.
- **[LOW]** Exact formatter matching by entity name means `MarketSlice(ticker="NVDA")` won't attach to entity `"NVIDIA"` without an alias layer.

**Suggestions:**
- Decide explicitly whether `inject_seed` must emit ticker symbols, or add a normalization step before `get_prices()`.
- Add a test with `SeedEntity(name="NVIDIA")` and document expected behavior.
- Strengthen redaction coverage with actual structlog events containing sensitive-looking values inside a packet/headline.
- In run_simulation tests, patch or configure all downstream Round 2/3 dependencies.
- Consider logging `context_assembly_skipped` at `info` level to reduce noise.

**Risk: MEDIUM to HIGH** — implementation path is sound, but ticker/entity mismatch can materially reduce feature value while still producing green tests.

---

### Plan 03

**Summary:** Plan 03 correctly targets both user-facing paths. Extending `AppState` is reasonable. The main issues are test strategy and an overstated end-to-end claim: the proposed "end-to-end" test patches `run_round1`, so it doesn't prove `AgentWorker.infer` receives the market context system message.

**Strengths:**
- Wires both web and CLI paths.
- `AppState` provider fields are a clean dependency path.
- Storing provider instances on both `app.state` and `app_state` is pragmatic and testable.
- CLI/web parity follows D-10/D-11.

**Concerns:**
- **[HIGH]** `test_lifespan_wires_providers` uses production `create_app()` with `TestClient`. Current web tests use `_make_test_app()` to avoid `.env`, Neo4j, and Ollama side effects — production lifespan can make this test flaky.
- **[MEDIUM]** The "end-to-end" test patches `run_round1` — only proves `run_simulation → run_round1` receives a string, not that `AgentWorker.infer` gets the formatted message.
- **[MEDIUM]** Importing real providers at top-level in `cli.py` loads `yfinance`, `feedparser`, `httpx` for all CLI commands — local import inside `_run_pipeline` would be lighter.
- **[MEDIUM]** Existing `SimulationManager` tests using `MagicMock` app states may pass `MagicMock` provider fields unless tests explicitly set them to `None`.

**Suggestions:**
- Test provider lifespan wiring by updating `_make_test_app()` to mirror provider wiring rather than using production lifespan.
- Extend `SimulationManager._run` test to assert `market_provider` and `news_provider` are forwarded.
- Rename or deepen the "end-to-end" test to go through dispatch/worker with mocked Ollama.
- Move provider imports in CLI inside `_run_pipeline`.

**Risk: MEDIUM** — wiring is straightforward, but planned tests can be misleading or flaky.

**Final Verdict:** Plans are directionally correct. Largest product risk is silent loss of market-price context when extracted entities are company names rather than tickers.

---

## Consensus Summary

### Agreed Strengths
- **Peer context pattern mirroring** (both reviewers): threading `market_context` as a scalar `str | None` mirroring `peer_context` is the correct architectural choice — battle-tested and minimal
- **TDD structure** (both reviewers): Wave 0 failing tests before implementation is well-executed and the test specifications are concrete
- **API correction** (both reviewers): using `get_prices()` instead of CONTEXT.md's incorrect `fetch_batch` prevents a runtime AttributeError
- **Backward compatibility** (both reviewers): all new params default to `None`, no breaking changes
- **`fetch_failed` filtering** (both reviewers): formatter correctly skips failed slices and returns `None` to avoid empty system messages

### Agreed Concerns

**1. [MEDIUM] Existing dispatcher mock tests need updating (Plan 01)**
Both reviewers flag that adding `market_context` as a positional arg to `_safe_agent_inference` will break existing mock-based dispatcher tests that don't expect the new parameter. The plan mentions this is an existing mock-heavy test suite.
- **Resolution:** Executor must audit all `_safe_agent_inference` call sites in tests and update mock signatures to accept `market_context: str | None = None`.

**2. [HIGH — Codex only, worth investigating] Entity name vs. ticker mismatch (Plan 02)**
Codex raises that `SeedEntity.name` from orchestrator LLM output is likely a company name (`NVIDIA`) not a ticker (`NVDA`). The `_TICKER_RE` filter would route these to `get_headlines` only, silently producing no market price data for most real seeds. Tests pass because fixtures use ticker-shaped names.
- **Resolution (pre-execution):** Verify what `inject_seed` actually produces for entity names against real seeds. If company names dominate, the phase delivers a half-feature. Consider documenting this as a known limitation in plan acceptance criteria.

**3. [MEDIUM] "End-to-end" test claim vs. reality (Plan 03)**
Both reviewers note that Plan 03's integration test patches `run_round1`, meaning it proves `run_simulation → run_round1` receives a string but not that `AgentWorker.infer` actually includes the market context system message. The test is valuable but misleadingly named.
- **Resolution:** Either rename the test to reflect its actual scope or extend it to go through `dispatch_wave` and verify messages structure in the worker.

**4. [MEDIUM] Lifespan test isolation (Plan 03)**
Both reviewers (Codex explicitly) flag that using production `create_app()` in lifespan tests conflicts with the project's `_make_test_app()` isolation pattern.
- **Resolution:** Use `_make_test_app()` extended with provider construction, or patch environment setup, to avoid Neo4j/Ollama dependencies in the lifespan test.

### Divergent Views

- **Risk level for Plan 02:** Gemini rates LOW, Codex rates MEDIUM-HIGH. The divergence is on the ticker/entity name issue — Gemini treats `_TICKER_RE` as defense-in-depth, Codex treats it as a potentially silent feature degradation. Worth confirming against actual `inject_seed` output before execution.
- **`_safe_agent_inference` positional arg:** Gemini accepts it as low-risk (private function, only one consumer). Codex recommends keyword forwarding as cleaner. Both are correct — keyword arg is safer style but positional works here.

---

*Reviewed 2026-04-19 by Gemini and Codex (Claude skipped — current runtime, independence required)*
