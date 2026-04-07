---
phase: 18
reviewers: [gemini, codex]
reviewed_at: 2026-04-07T03:19:10Z
plans_reviewed: [18-01-PLAN.md, 18-02-PLAN.md, 18-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 18

## Gemini Review

This review evaluates **Phase 18: Agent Context Enrichment and Enhanced Decisions**, which introduces bracket-specific market data enrichment and extended structured output for 100 agents.

### 1. Summary
The implementation plans (18-01 to 18-03) provide a robust and surgically precise approach to grounding agent decisions in real-market data. The strategy successfully bypasses the shared `user_message` constraint of the batch dispatcher by utilizing a **sub-wave dispatch architecture**. The data models are extended with backward compatibility in mind, ensuring that the transition to more complex JSON outputs does not break existing simulation stability. The inclusion of news headlines with graceful degradation completes a critical deferred requirement from Phase 17.

### 2. Strengths
- **Sub-Wave Dispatch Strategy:** The decision to split each round into three sub-waves in `simulation.py` is the most elegant solution to providing bracket-specific context without refactoring the core `dispatch_wave` or `AgentWorker` interfaces.
- **Backward Compatibility:** The use of `ticker_decisions: list[TickerDecision] = Field(default_factory=list)` ensures that older or failing agent versions won't trigger `PARSE_ERROR` states, maintaining simulation continuity.
- **Graceful Degradation:** Plan 18-02 handles the restrictive Alpha Vantage rate limits (25 calls/day) by allowing headlines to be skipped with a warning, preventing API exhaustion from being a fatal error.
- **Consistent Data Slicing:** The logical grouping of 10 brackets into 3 data slices (Technicals, Fundamentals, Earnings) is well-aligned with the agent personas' intended behaviors.
- **Alignment Logic:** Task 2.3 in Plan 18-03 explicitly addresses the potential pitfall of positional misalignment by merging sub-wave results back into the original persona order using `agent_id` lookups.

### 3. Concerns
- **MEDIUM — Alpha Vantage Quota Exhaustion:** Headlines are not cached after fetch. `enrich_snapshots_with_headlines` is called post-`fetch_market_data`, meaning a cached snapshot will still trigger AV every run. With 3 tickers and a 25-call daily limit, quota can exhaust within 2-3 simulation runs.
- **LOW — Sequential Sub-Wave Performance:** Plan 18-03 processes the three bracket groups sequentially (`for ...: await dispatch_wave`). Safer for memory, but increases total simulation time vs. the previous single-wave dispatch.
- **MEDIUM — JSON Schema Complexity vs. Qwen 9B:** Adding an array of objects (`ticker_decisions`) significantly increases the surface area for JSON syntax errors. The 3-tier fallback helps, but the `JSON_OUTPUT_INSTRUCTIONS` must be extremely clear.
- **MEDIUM — Token Budget Pressure:** With `MAX_MARKET_BLOCK_CHARS` reaching up to 2000 characters for the Earnings slice, and current system prompts already near 90% capacity, there is risk of context window overflow for agents with long peer contexts.

### 4. Suggestions
- **Headline Caching:** Modify `enrich_snapshots_with_headlines` to check if `snapshot.headlines` is already populated before calling AV, or ensure enriched snapshots pass back to the cache manager.
- **Truncation Indicator:** Consider appending "..." to truncated market blocks so the agent knows it is seeing partial data.
- **time_horizon prompt:** In `JSON_OUTPUT_INSTRUCTIONS`, list valid `time_horizon` strings as a set rather than free-form to help qwen3.5:9b stay consistent.
- **Monitoring:** Add a `structlog` metric for total character count of the enriched `user_message` to calibrate `MAX_MARKET_BLOCK_CHARS` after first runs.

### 5. Risk Assessment: LOW
The plans are highly surgical, preserve all existing invariants, and provide clear paths for failure recovery. The most significant risk — Ollama context window overflow — is well-managed by the character cap constants. The dependency chain is respected and the transition from Phase 17 is seamless.

---

## Codex Review

### Cross-Plan Blockers
The plan set is mostly well-scoped, but it does not yet achieve Phase 18 end-to-end. The biggest gap is that simulation only fetches market data when `parsed_result.seed_event.tickers` is populated, while the current seed prompt and parser path may not populate tickers at all. If that is not handled elsewhere, all three plans can land and enrichment still never runs. The other major issue is dependency ordering: 18-03 depends only on 18-01, but it imports and calls headline enrichment that 18-02 introduces.

### 18-01-PLAN.md

**Summary:** Solid foundational split: data model extension, prompt contract update, and enrichment formatting in one place. The plan is clear and test-oriented, but weaker on malformed-output resilience than it claims, and the token-budget story is still approximate rather than validated.

**Strengths:**
- Clean separation of concerns: model contract in `types.py`, prompt schema in `config.py`, formatting in new `enrichment.py`.
- Good backward-compatibility intent with `ticker_decisions: []` defaults.
- Bracket grouping is simple and implementable.
- TDD coverage for missing-field fallback is appropriate.

**Concerns:**
- `HIGH:` The current parser is strict full-model validation. Missing `ticker_decisions` will be fine, but malformed nested values will still collapse the whole response to `PARSE_ERROR`. The plan tests only the missing-field case, not the malformed-field case.
- `MEDIUM:` Reusing `SignalType` for `TickerDecision.direction` also permits `"parse_error"`, which is not a valid business decision for a ticker.
- `MEDIUM:` The char-cap approach is pragmatic, but STATE.md explicitly flags tokenizer validation as a Phase 18 concern. This plan does not include any calibration test, so "strict token budget" is not actually proven.
- `MEDIUM:` The earnings slice plus 10 headlines per ticker conflicts with the 2000-char cap if 2-3 tickers are present. Later tickers can be truncated away entirely, working against the "every agent sees all tickers" requirement.
- `LOW:` The JSON example is fairly long and gets appended to every persona prompt — adds prompt bloat across 100 agents.

**Suggestions:**
- Add parser tests for malformed `ticker_decisions`, not just missing ones.
- Consider a lenient parse path that drops invalid `ticker_decisions` entries while preserving the top-level decision.
- Narrow `direction` to `buy|sell|hold` without exposing `parse_error`.
- Keep 10 headlines in the snapshot if needed, but budget fewer into the prompt block.
- Add one calibration test or fixture measuring rough token count against the target qwen tokenizer.

**Risk Assessment: MEDIUM** — module split is good, but parse robustness and budget enforcement are not yet strong enough to guarantee the phase success criteria.

---

### 18-02-PLAN.md

**Summary:** The most bounded plan of the three. Fits the async/local architecture, degrades gracefully, and avoids overengineering. Main weakness is that it stores/fetches headlines without clearly reconciling that volume with the prompt-budget constraints from 18-01.

**Strengths:**
- Graceful degradation on missing API key and per-ticker fetch failure.
- Uses frozen-model `model_copy`, which matches the current `MarketDataSnapshot` contract.
- Sequential fetches are a reasonable choice for AV's low rate limits and max-3-ticker constraint.
- Tests cover the key happy path and failure path behaviors.

**Concerns:**
- `MEDIUM:` Fetching 10 headlines per ticker is fine for storage, but if downstream formatting also injects 10 per ticker, this plan contributes directly to prompt overflow risk.
- `MEDIUM:` No caching/reuse strategy for headlines. With AV's free-tier limits, repeated local runs can exhaust quota quickly even if production usage is modest.
- `LOW:` `fetch_headlines()` opens a new `httpx.AsyncClient` per ticker. With max 3 tickers acceptable, but a shared client would be cleaner.
- `LOW:` Plan does not explicitly cover non-200 responses or invalid JSON payloads.

**Suggestions:**
- Clarify that "fetch 10" and "inject 10" are different concerns; fetch/store 10, inject fewer under budget.
- Reuse one `AsyncClient` inside `enrich_snapshots_with_headlines()`.
- Add one test for HTTP error / invalid JSON handling.
- Document that repeated dev runs can hit AV daily limits.

**Risk Assessment: MEDIUM** — implementation itself is straightforward, but output volume can undermine prompt-budget goals unless 18-01/18-03 constrain injection more tightly.

---

### 18-03-PLAN.md

**Summary:** Architecturally the right response to the `dispatch_wave()` constraint. Strong on preserving positional ordering, but has the largest completeness risks of all three plans.

**Strengths:**
- Correctly identifies the shared-`user_message` constraint and solves it without changing worker/message architecture.
- Preserves backward compatibility when no market snapshots exist.
- Merging by `agent_id` back into original persona order is the right invariant for downstream writes.
- Pre-round headline enrichment once (not per round) is the right performance shape.

**Concerns:**
- `HIGH:` Dependency bug: 18-03 depends only on 18-01 but calls `enrich_snapshots_with_headlines`, which 18-02 introduces. Wave-2 parallel execution is unsafe as written.
- `HIGH:` End-to-end incompleteness: if `SeedEvent.tickers` is never populated, `simulation.py` keeps `market_snapshots` empty and all new dispatch logic falls back to bare-rumor behavior. Phase goal missed even if plan is implemented perfectly.
- `HIGH:` The roadmap says Macro agents should see sector-level data, but the locked slice design and this plan place Macro in the Earnings/Headlines group. This is a spec mismatch, not just an implementation detail.
- `MEDIUM:` Splitting one wave into three changes wave-level failure accounting — governor shrink behavior differs from today.
- `MEDIUM:` Converting `peer_contexts` from list to dict via `zip()` can hide length mismatches that `dispatch_wave()` currently guards against.
- `LOW:` Task 1 uses test stubs and `--collect-only`, which is weaker than true red-green TDD.

**Suggestions:**
- Make 18-03 depend on 18-02, or move the headline-enrichment call into 18-02 and keep 18-03 strictly about dispatch wiring.
- Add a prerequisite plan or extend this phase to verify `SeedEvent.tickers` is populated from seed parsing.
- Resolve the Macro-agent success-criteria mismatch before implementation starts.
- Add explicit invariants for `peer_context` count and per-group decision count before merging.

**Risk Assessment: HIGH** — architecture is sound, but the dependency graph and missing ticker-extraction path mean this plan does not reliably make Phase 18 live.

### Overall Risk: HIGH
The main reason is not code complexity — it is completeness. Fix the missing ticker-population path, make 18-03 depend on 18-02, and resolve the Macro-slice spec mismatch; after that, remaining risk drops to roughly MEDIUM.

---

## Consensus Summary

### Agreed Strengths
- Sub-wave dispatch architecture is the correct and elegant solution to the shared `user_message` constraint
- Backward-compatible `ticker_decisions: []` default is correctly engineered
- Graceful degradation for missing AV key / rate limits is well-handled
- `model_copy(update={"headlines": ...})` for frozen snapshots is the right pattern

### Agreed Concerns

**1. Alpha Vantage quota + headline caching (MEDIUM — both reviewers)**
No caching for headline fetches. Repeated local dev runs can exhaust the 25-call/day free tier. The plan should either reuse market data cache for headlines, or document the quota risk prominently.

**2. Headline volume vs. prompt budget (MEDIUM — both reviewers)**
"Fetch 10 headlines" and "inject 10 headlines" should be treated as separate concerns. The 2000-char cap for Earnings/Insider brackets can easily be consumed by 10 headlines × 120 chars per ticker, leaving no room for the structured financial fields — especially with 2-3 tickers.

**3. JSON schema complexity for qwen3.5:9b (MEDIUM — both reviewers)**
The nested `ticker_decisions` array significantly increases parse failure surface. The 3-tier fallback handles missing fields, but Codex flags that malformed nested values still collapse to PARSE_ERROR — a gap the tests don't cover.

### Divergent Views

**Dependency order (Codex: HIGH, Gemini: not flagged)**
Codex identified a concrete bug: 18-03 depends only on 18-01 but calls `enrich_snapshots_with_headlines` from 18-02. If wave-2 plans run in parallel, 18-03 may execute before 18-02 ships the function. Gemini did not flag this. This should be fixed by updating 18-03's `depends_on` to include `18-02`.

**End-to-end ticker path (Codex: HIGH, Gemini: not flagged)**
Codex flagged that `SeedEvent.tickers` may not be populated by the current seed/parser path, meaning enrichment never runs even with perfect implementation. This warrants verification against Phase 16/17 code before execution.

**Macro-agent spec mismatch (Codex: HIGH, Gemini: not flagged)**
The roadmap success criteria says "Macro agents see sector-level data" but the CONTEXT.md locked decision places Macro in the Earnings/Insider slice (headlines + surprise). Codex flagged this as a spec conflict; Gemini did not. Needs resolution with user before planning proceeds.

**Overall risk level (Codex: HIGH, Gemini: LOW)**
Reviewers diverged significantly. Gemini evaluated implementation quality and found it LOW risk. Codex evaluated end-to-end completeness and found it HIGH risk due to the ticker population gap and dependency bug. Both assessments are valid from their lens.
