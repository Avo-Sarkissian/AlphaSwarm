---
phase: 39
reviewers: [gemini]
skipped: [claude (current runtime), codex (empty output — failed)]
reviewed_at: 2026-04-19T05:14:43Z
plans_reviewed: [39-01-PLAN.md, 39-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 39

## Gemini Review

This review evaluates **Phase 39: Holdings Loader**, focusing on the implementation of the `HoldingsLoader` and its integration into the FastAPI web layer while maintaining the strict isolation boundaries required for AlphaSwarm.

### Summary

The proposed plans are architecturally sound and demonstrate a deep understanding of the project's technical constraints, particularly regarding **data isolation** and **numeric precision**. By utilizing eager loading during the FastAPI lifespan and enforcing `Decimal` string serialization, the plan effectively addresses both performance and accuracy risks. The strategy for hashing account numbers and the inclusion of exhaustive unit tests—including grep-based invariants to prevent logging leaks—shows a high level of rigor. The dependency management via `importlinter` is correctly handled without unnecessary modifications to the core configuration.

### Strengths

- **Precision Safety:** Mandating `Decimal(string)` and prohibiting `Decimal(float)` prevents the subtle rounding errors common with fractional shares in financial data.
- **Performance Optimization:** The "eager load at lifespan" pattern ensures the `GET /api/holdings` endpoint remains high-performance and non-blocking, adhering to the project's async-first mandate.
- **Security & Isolation:** The use of `sha256_first8` for deterministic hashing and the "grep invariant" tests to prevent PII logging provides strong protection against accidental data leakage (ISOL-07).
- **Resiliency:** The 503 error handling for malformed/missing CSVs prevents a single data issue from crashing the entire simulation or WebSocket loop, ensuring system stability.
- **Deterministic Hashing:** Sorting account labels before joining and hashing ensures that the `account_number_hash` is stable regardless of the row order in the CSV.

### Concerns

- **[LOW] Merge Logic Ambiguity:** Plan 01 mentions "collapsing" accounts into a single snapshot. If the same ticker exists in both the `individual` and `roth_ira` accounts, it is unclear if the loader should sum these positions or represent them as separate entries in the `holdings` tuple. While separate entries are often safer for audit trails, summed totals are typically better for "Advisory" ranking.
- **[LOW] Startup Failure Visibility:** While storing `None` and returning a 503 is safe, if the holdings file is critical for the "Advisory" milestone, a failed load at startup might be a silent failure for a user who doesn't check the logs or the specific endpoint.
- **[MEDIUM] CSV Header Sensitivity:** The plan relies on `csv.DictReader`. If Schwab changes their export header names (e.g., "Shares" vs "Quantity"), the loader will fail. The plan mentions header validation, which is good, but a specific "header mapping" or "alias" system might be more robust for long-term maintenance.

### Suggestions

- **Clarify Merging Strategy:** Explicitly define whether multiple rows of the same ticker should be summed. For an "Advisory" synthesis, a single merged position (sum of quantity, weighted average of cost basis) is usually preferred to prevent the AI from processing the same asset multiple times.
- **Extended Path Validation:** In the lifespan logic, consider checking if the `Schwab/` directory exists and has correct permissions even if the file is missing, to provide more descriptive "unavailability" logs.
- **Schema Enforcement:** Explicitly list the expected CSV header strings in a constant within `loader.py` to make the code easier to update if the Schwab export format evolves (REQUIRED_COLUMNS frozenset already does this — confirm it's the sole source of truth).
- **Canary Verification:** Ensure the `test_loader_module_does_not_log_holding_field_values` grep test specifically checks for `ticker`, `qty`, and `cost_basis` to ensure the ISOL-07 boundary is actually enforced during implementation.

### Risk Assessment: LOW

The plan is exceptionally low-risk. It follows established Python idioms for financial data, respects the project's complex isolation constraints, and includes a comprehensive testing strategy. The decoupling of the loader from the web route and the use of cached state effectively mitigates the most common pitfalls of file-backed REST APIs.

**Justification:**
1. Strict adherence to `Decimal` types eliminates precision risk.
2. Eager loading eliminates I/O-related concurrency bottlenecks in the web loop.
3. Import-linter and grep-based tests provide a double-layered defense for the isolation requirements.

---

## Codex Review

Codex CLI returned empty output — review unavailable.

---

## Consensus Summary

One reviewer (Gemini) completed successfully. Claude skipped as current runtime.

### Agreed Strengths

- Decimal(string) precision discipline — critical for fractional share accuracy
- Eager lifespan load pattern is correct for the async-first constraint
- 503 isolation ensuring CSV failures don't crash the WebSocket loop
- Deterministic sha256_first8 hash with sorted account labels
- Importlinter contract handled correctly without pyproject.toml edits

### Agreed Concerns

- **[MEDIUM] CSV header sensitivity:** No version pinning or alias mapping if Schwab export format evolves. REQUIRED_COLUMNS frozenset is the guard — confirm it's complete and documented as the sole validation point.
- **[LOW] Same-ticker multi-account behavior:** D-03 specifies a single merged tuple but doesn't define behavior when the same ticker appears in both accounts (individual + roth_ira AAPL, for example). The real CSV may not have overlaps, but the test suite doesn't explicitly cover this case. Phase 41 advisory synthesis may need to handle duplicate tickers in the holdings tuple.
- **[LOW] Startup failure observability:** A HoldingsLoadError at lifespan is logged server-side but yields a silent 503 until the endpoint is hit. Consider a startup banner or health check endpoint exposing holdings load status.

### Divergent Views

No divergent views — single reviewer.

### Action Items for Planning

1. **Confirm ticker-dedup policy** in Plan 01 must_haves: is a CSV with `individual,AAPL,...` AND `roth_ira,AAPL,...` valid, and if so does the tuple have 2 entries or 1 merged entry?
2. **Add a test** `test_same_ticker_multiple_accounts` to make the dedup behavior explicit (even if the answer is "two separate entries" — just make it a documented contract).
3. **REQUIRED_COLUMNS** is correct guard for header evolution — no alias system needed, but confirm the error message names the missing column(s) so operators know what to fix.
