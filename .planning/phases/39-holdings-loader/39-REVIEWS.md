---
phase: 39
reviewers: [gemini, codex]
skipped: [claude (current runtime)]
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

Codex reviewed the plans against the current repo structure. Overall, Plan 01 is solid and narrowly scoped. Plan 02 has the bigger risk because the proposed lifespan wiring can conflict with the existing importlinter boundary.

### Plan 01 Summary

Plan 01 is well-scoped and directly addresses HOLD-01/HOLD-02. The loader design matches the existing immutable dataclass model in `types.py` and correctly emphasizes Decimal parsing, tuple immutability, deterministic account hashing, and no logging of holding values. Risk is mostly around CSV edge cases and ensuring the synchronous loader is only called from a safe context.

### Plan 01 Strengths

- Correctly uses `Decimal(string)` and computes total cost basis from per-share basis.
- Preserves the existing immutable `PortfolioSnapshot.holdings: tuple[Holding, ...]` contract.
- Handles the important HOLD-02 issue by hashing before constructing the snapshot.
- Test plan is strong: precision, row order, header-only CSV, missing files, sort-stable account hash, and money-market inclusion are all useful coverage.
- Avoids pyproject/importlinter churn, which matches the current coverage rule that exempts `alphaswarm.holdings.*`.

### Plan 01 Concerns

- **[MEDIUM] Loader is synchronous:** Fine as a pure loader API, but Plan 02 must not call it directly on the async FastAPI event loop.
- **[MEDIUM] Incomplete CSV malformed handling:** Should explicitly cover blank/whitespace-only fields, blank account labels, blank symbols, and UTF-8 BOM headers. Schwab CSVs can surprise parsers even when the expected file is simple.
- **[LOW] Source-grep tests fragility:** Tests for "never Decimal(float)" and "does not log holding values" are useful guards but can be brittle — may false-pass or false-fail depending on comments/import formatting.
- **[LOW] Re-exporting HoldingsLoader from `__init__`:** Broadens package import side effects. Acceptable only if `loader.py` stays stdlib/lightweight and avoids structlog or web dependencies (it does — structlog is fine since it's already a project dep).

### Plan 01 Suggestions

- Open CSV with `encoding="utf-8-sig"` and `newline=""` to handle BOM.
- Strip header names and field values before validation.
- Include row numbers in `HoldingsLoadError` messages (but not raw ticker/account/qty/cost values).
- Add tests for blank account, blank symbol, blank numeric field, whitespace-padded headers/values.

### Plan 01 Risk Assessment: LOW-MEDIUM

The implementation is conceptually simple and well-tested. The main risk is not the loader itself, but accidental event-loop blocking or overly narrow CSV validation.

---

### Plan 02 Summary

Plan 02 covers the right product behavior: eager load once, cache on `app.state`, serialize Decimals as strings, and return 503 when unavailable. However, the current repo's importlinter contract makes the proposed `web.app` lifespan wiring risky. `pyproject.toml` lists `alphaswarm.web.app` as a forbidden source module, while only `alphaswarm.web.routes.holdings` is intended to touch `alphaswarm.holdings`. A direct `HoldingsLoader` import in `web/app.py` would violate the architecture.

### Plan 02 Strengths

- Correctly avoids disk I/O per request by using `app.state.portfolio_snapshot`.
- Correctly serializes `Decimal` values as strings instead of floats.
- Uses a clear 503 unavailable state instead of letting startup CSV failures break WebSocket/broadcaster setup.
- Places the endpoint in the intended whitelisted module name, `alphaswarm.web.routes.holdings`.
- Integration tests avoid reading the real Schwab file, which is the right isolation choice.

### Plan 02 Concerns

- **[HIGH] Import boundary conflict:** `web.app` must not directly import `alphaswarm.holdings` or `HoldingsLoader`. The current contract explicitly includes `alphaswarm.web.app` in forbidden `source_modules`. The plan's key_links show `from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError` inside `web/app.py` — this needs importlinter verification before coding.
- **[HIGH] Indirect import detection:** Even if `web.app` only imports `alphaswarm.web.routes.holdings`, importlinter may still detect an indirect path to `alphaswarm.holdings` depending on contract behavior. The "pyproject receives ZERO edits" assumption needs proof after route registration.
- **[MEDIUM] Blocking I/O in async lifespan:** Calling `HoldingsLoader.load(path)` inside async lifespan is blocking I/O on the event loop. Startup blocking is lower blast radius than request blocking, but it conflicts with the project's CLAUDE.md Hard Constraint 1 (no blocking I/O on the main event loop).
- **[MEDIUM] 503 response body shape:** If the route raises `HTTPException(detail={...})`, FastAPI returns `{"detail": {...}}`, not the planned top-level `{"error": ..., "message": ...}` body. Test assertions need to match actual FastAPI wrapping.
- **[MEDIUM] Integration tests cover proxy state but not production wiring:** Tests seed `app.state.portfolio_snapshot` directly but don't verify production lifespan behavior: configured path use, loader failure capture, startup continuation, and route registration in `create_app()`.
- **[LOW] AppSettings config tests:** `holdings_csv_path` needs config tests for default and `ALPHASWARM_HOLDINGS_CSV_PATH` override.

### Plan 02 Suggestions

- Make the import boundary explicit before implementation. Run `uv run lint-imports` immediately after adding the `HoldingsLoader` import to `web/app.py` to confirm it passes. If it fails, either route the loader call through `web.routes.holdings` or add a targeted importlinter exception.
- Wrap the loader call with `await asyncio.to_thread(HoldingsLoader.load, settings.holdings_csv_path)` to avoid blocking the event loop during lifespan startup.
- Initialize `app.state.portfolio_snapshot = None` before attempting load, then replace it on success.
- Use `JSONResponse(status_code=503, content={...})` if the response must be top-level `{"error": ..., "message": ...}`; otherwise update the plan/tests to expect FastAPI's `{"detail": {...}}` wrapper.
- Add production-wiring tests: `/api/holdings` registered in `create_app()`, lifespan stores a loaded snapshot when the loader succeeds, and lifespan stores `None` when `HoldingsLoadError` is raised.

### Plan 02 Risk Assessment: MEDIUM-HIGH

The endpoint behavior is straightforward, but the importlinter boundary and async lifespan details are material risks. Resolve those before coding; otherwise the implementation may pass route tests but fail architecture invariants.

---

## Consensus Summary

Both reviewers (Gemini + Codex) completed. Claude skipped as current runtime.

### Agreed Strengths

- `Decimal(string)` precision discipline — critical for fractional share accuracy, both reviewers confirmed
- Eager lifespan load pattern is correct for the async-first constraint
- 503 isolation ensuring CSV failures don't crash the WebSocket loop
- Deterministic `sha256_first8` hash with sorted account labels
- Test plan comprehensiveness for Plan 01 (error paths, edge cases, grep invariants)
- Integration tests using hermetic `app.state` seeding rather than real Schwab CSV

### Agreed Concerns

- **[HIGH — Codex only] Import boundary in `web.app`:** Both reviewers flag isolation as a strength, but Codex specifically identified that `web.app` importing from `alphaswarm.holdings.loader` may violate the importlinter `source_modules` contract. This needs `uv run lint-imports` verification BEFORE the Plan 02 executor writes any code. If `web.app` is a forbidden source module, the lifespan must route through a different mechanism (e.g., pass the loader function in via the route module, or use `asyncio.to_thread` with the import inside the whitelisted route).
- **[MEDIUM] Blocking I/O in async lifespan:** Gemini accepted the lifespan-load pattern; Codex flagged it as a constraint violation. CLAUDE.md Hard Constraint 1 ("No blocking I/O on the main event loop") technically covers the lifespan context. `asyncio.to_thread(HoldingsLoader.load, path)` is the clean fix.
- **[MEDIUM] 503 response body FastAPI wrapping:** `HTTPException(detail={...})` wraps the dict in `{"detail": {...}}`. If tests assert top-level `{"error": ..., "message": ...}`, they will fail. Use `JSONResponse` for top-level shape or update must_haves to reflect the actual body.
- **[MEDIUM — Gemini] CSV header sensitivity:** Schwab may change header names. `REQUIRED_COLUMNS` frozenset is the guard — confirm error messages name missing columns explicitly.
- **[LOW] Same-ticker multi-account behavior undefined:** D-03 merges accounts but doesn't specify what happens when both `individual` and `roth_ira` hold the same ticker. Test suite should add a `test_same_ticker_multiple_accounts` case documenting the contract (likely: two separate Holding entries, not summed).
- **[LOW] Startup failure observability:** HoldingsLoadError at lifespan is logged server-side only. A health/status endpoint or startup log banner would surface the failure without requiring a GET /api/holdings probe.

### Divergent Views

- **Gemini** rated Plan 02 overall LOW risk; **Codex** rated it MEDIUM-HIGH due to the importlinter boundary and async lifespan concerns. Codex's concern about the import boundary in `web.app` is the key difference and should be verified against the live importlinter config before dismissing.
- **Gemini** suggested an alias/mapping system for CSV header evolution; **Codex** suggested open with `utf-8-sig` for BOM handling. Both are reasonable defensive additions; neither is required for v6.0.

### Action Items for Plan 02 Executor

1. **Before writing any code:** Run `uv run lint-imports` after adding `from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError` to `web/app.py`. If it fails, the lifespan wiring approach must change.
2. **Async fix:** Replace `HoldingsLoader.load(settings.holdings_csv_path)` in lifespan with `await asyncio.to_thread(HoldingsLoader.load, settings.holdings_csv_path)`.
3. **503 body:** Verify whether `HTTPException(detail={...})` or `JSONResponse(content={...})` produces the expected response shape, and align must_haves accordingly.
4. **Plan 01 executor:** Add `test_same_ticker_multiple_accounts` to document the dedup contract.
5. **Plan 01 executor:** Consider opening CSV with `encoding="utf-8-sig"` to handle BOM-prefixed Schwab exports.
