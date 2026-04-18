---
phase: 38
reviewers: [gemini, codex]
reviewed_at: 2026-04-18T17:47:00Z
plans_reviewed: [38-01-PLAN.md, 38-02-PLAN.md, 38-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 38

## Gemini Review

This review evaluates the implementation plans for **Phase 38: Market Data + News Providers**. The plans demonstrate a high level of technical maturity, specifically in their handling of asynchronous boundaries and the known idiosyncrasies of the `yfinance` and `feedparser` libraries.

### 1. Summary
The Phase 38 plan set is exceptionally robust, directly addressing the "never-raise" (D-19) and async-first requirements while proactively mitigating documented pitfalls discovered during research (e.g., `yfinance` delisting errors and `feedparser` timezone skews). The architecture correctly separates the sync-heavy `yfinance` logic into threads and utilizes `httpx` for efficient RSS ingestion. The inclusion of the "cross-AI" fixes—specifically `calendar.timegm` for UTC consistency and `_decimal_or_none` for data integrity—ensures the simulation receives grounded, high-quality context without risking event-loop blockage.

### 2. Strengths
- **Performance Optimization:** Plan 38-01's use of a shared `_fetch_batch_shared` helper is a smart design choice. Since `yfinance` fetches most data in a single network request, this prevents tripling the I/O overhead for a single ticker.
- **Data Integrity:** The implementation of `_decimal_or_none` using `Decimal(str(value))` (Pitfall 5) and explicit guards for `NaN/Inf` ensures that the simulation logic won't crash on invalid financial ratios.
- **Resilience (Never-Raise):** The plans strictly adhere to the D-19 mandate. By converting all exceptions into `fetch_failed` states at the provider level, the simulation governor remains insulated from external API instability.
- **Security & Sanitization:** Plan 38-02 correctly balances flexibility and security by using strict regex for tickers while employing `quote_plus` for general entities to prevent URL injection in the Google News RSS path.
- **Test Rigor:** The integration tests (Plan 38-03) include a "tolerant" assertion strategy for unknown tickers, which is critical for CI stability when dealing with the non-deterministic nature of live market data.

### 3. Concerns
- **Ticker Regex Bias (MEDIUM):** The RSS routing regex `^[A-Z]{1,5}$` is strictly tuned for US-listed tickers. If a "Seed Rumor" includes international assets (e.g., `VOD.L` or `SHOP.TO`), they will be routed to Google News search rather than the structured Yahoo Finance RSS feed.
- **Thread Pool Exhaustion (LOW):** Plan 38-01 uses `asyncio.to_thread` per ticker. While D-07 notes these are called once per simulation, a "Seed Rumor" referencing a very high number of tickers (e.g., 50+) could lead to a temporary spike in thread creation.
- **HTTP Client Lifecycle (LOW):** Plan 38-02 mentions `httpx.AsyncClient` timeouts but does not explicitly state the lifecycle of the client. Creating a new client per `get_headlines` call is less efficient than using a single client across the `asyncio.gather` batch.

### 4. Suggestions
- **RSS Routing Refinement:** Consider updating the `_TICKER_RE` to `^[A-Z]{1,5}(\.[A-Z]{1,2})?$` to support common international suffixes if the project roadmap anticipates global market support.
- **Client Management:** In `RSSNewsProvider`, ensure the `httpx.AsyncClient` is used as an asynchronous context manager within the batch fetching logic to ensure proper connection pooling and socket closure.
- **Logging Context:** Given the "never-raise" requirement, ensure that when an exception is caught and converted to a `fetch_failed` slice, the original exception is logged with `structlog.exception` to allow for post-simulation debugging of data gaps.
- **YFinance Version Lock:** While the plan specifies `>=1.3.0,<2.0`, `yfinance` is notorious for breaking changes. Consider a more restrictive pin (e.g., `~=1.3.0`) in `pyproject.toml` if the current environment is stable.

### 5. Risk Assessment: LOW
The overall risk is **LOW**. The plans are highly defensive, account for library-specific edge cases, and provide a clear path for verification via integration tests. The "never-raise" architecture ensures that even if external providers fail or change their data format, the core AlphaSwarm simulation will degrade gracefully rather than crash. The incorporation of all prior cross-review feedback (NaN guards, timeout consensus, and timezone fixes) indicates a high degree of readiness for implementation.

---

## Codex Review

### Summary

Phase 38 is generally well-scoped and the plan set addresses INGEST-01 and INGEST-02 without drifting into Phase 40 simulation wiring. The async boundary choices are mostly sound: yfinance is isolated behind `asyncio.to_thread`, RSS uses `httpx.AsyncClient`, failures are converted into typed failed slices, and live tests are correctly separated under `tests/integration/`. The main risks are dependency/version correctness, over-fetching and failure coupling in the yfinance provider, HTTP status handling in the RSS provider, and live integration test flakiness.

### Strengths

- Clear separation between provider implementation and later simulation wiring.
- Correctly incorporates the major cross-review fixes:
  - `Decimal(str(value))` instead of `Decimal(float)`.
  - NaN/Inf guard for fundamentals.
  - `calendar.timegm()` for RSS `published_parsed`.
  - `httpx` timeout at client/request level.
  - Tolerant live assertion for unknown/delisted yfinance tickers.
- Good async model: yfinance sync work in `asyncio.to_thread`; RSS network I/O via `httpx.AsyncClient`; batch fetches via `asyncio.gather`.
- Good test isolation: unit tests monkeypatch yfinance/httpx; live tests under `tests/integration/`; empty-list behavior explicitly tested for yfinance.
- RSS URL construction is mostly secure: ticker route uses strict regex; non-ticker entities are URL-encoded with `quote_plus`.

### Concerns

- **HIGH - yfinance version pin is currently unsatisfiable.** The plan pins `yfinance>=1.3.0,<2.0`, but PyPI currently lists `1.2.2` as the latest release as of April 13, 2026. This would block `uv sync` today. Use a tested available floor such as `>=1.2.2,<2.0` or whatever version the live probe actually used.

- **HIGH - RSS provider must call `response.raise_for_status()` or explicitly reject non-2xx responses.** Without that, a Yahoo 429 or Google error page can be parsed as an empty feed and incorrectly marked `fresh`. This directly weakens Pitfall 4 coverage and violates the intended `fetch_failed` behavior on provider failure.

- **MEDIUM - yfinance shared helper may over-fetch and couple unrelated failures.** If every call to `get_prices`, `get_volume`, and `get_fundamentals` fetches both `fast_info` and `.info`, then lightweight price/volume calls pay the expensive `.info` cost. Worse, a fundamentals `.info` failure can turn an otherwise valid price fetch into `fetch_failed`.

- **MEDIUM - shared yfinance helper does not prevent triple network cost across separate protocol calls.** Code reuse inside `_fetch_batch_shared` is good, but with D-10 no caching, calling all three protocol methods separately still performs multiple yfinance fetches. Phase 40 needs a clear call pattern.

- **MEDIUM - `asyncio.gather(return_exceptions=False)` is brittle for a never-raise contract.** Even if `_fetch_one_sync` is intended never to raise, a bug or unexpected wrapper error could break the whole batch. Using `return_exceptions=True` gives a stronger D-19 contract at the gather layer.

- **MEDIUM - RSS exact substring filtering may over-filter useful ticker news.** For ticker `AAPL`, Yahoo Finance RSS titles often say "Apple" rather than "AAPL". If the filter is strictly `entity.lower() in title.lower()`, ticker-routed feeds may return empty headlines even when relevant articles exist.

- **MEDIUM - RSS integration tests are likely flaky.** Assertions like `len >= 1` for `EV battery`, exact entity-filter verification against live Google News, and a live "User-Agent prevents 429" test depend on third-party behavior.

- **LOW - RSS empty-list behavior is not explicitly listed.** Pitfall 9 covers yfinance empty-list. RSS should have an explicit unit and integration test that `get_headlines([]) == {}`.

- **LOW - lockfile update is missing from file lists.** If `uv.lock` is tracked, both dependency tasks should update it in the same wave as `pyproject.toml`.

- **LOW - input size limits are not addressed.** A huge entity string from a seed rumor could create oversized URLs or noisy external requests. A conservative max entity length would make this more robust.

### Suggestions

- Change the yfinance dependency pin to a currently available tested version (`>=1.2.2,<2.0`).
- In `RSSNewsProvider._fetch_one`, add `response.raise_for_status()` before feedparser parse; add unit test asserting non-2xx becomes `_fetch_failed_news_slice`.
- Consider splitting yfinance fetch paths: `get_prices`/`get_volume` use only `fast_info`; `get_fundamentals` uses `.info`. Or add `include_fundamentals: bool` flag so price-only paths avoid `.info`.
- Document which single method Phase 40 should call to avoid duplicate provider work.
- Harden `_decimal_or_none` to return `None` on `InvalidOperation`, `TypeError`, string placeholders.
- For RSS ticker routes, document explicitly whether Yahoo Finance RSS is entity-scoped enough to skip title filtering.
- Convert the "User-Agent prevents 429" check into a unit-level header assertion; keep live RSS tests as smoke tests with tolerant assertions.
- Add an RSS empty-list test and include `uv.lock` in planned modified files.

### Risk Assessment: MEDIUM

The implementation direction is sound. The highest practical blocker is the yfinance version pin (appears invalid today). The highest behavioral risk is RSS status handling (silently marking failed HTTP responses as fresh). The highest future performance risk is yfinance over-fetching via `.info`, especially if Phase 40 calls multiple provider methods per simulation run.

---

## Consensus Summary

Phase 38 reviewed by 2 AI systems (Gemini, Codex).

### Agreed Strengths
- **D-19 never-raise architecture** — both reviewers praised the broad try/except approach converting all exceptions to typed failed slices; simulation governor insulated from external API instability
- **Async boundary design** — yfinance behind `asyncio.to_thread`, RSS via `httpx.AsyncClient`, batch fetches via `asyncio.gather` is universally considered correct
- **Cross-review fixes correctly incorporated** — Decimal NaN/Inf guard, `calendar.timegm`, timeout on client+request, tolerant delisted-ticker assertion all confirmed present
- **URL injection security** — strict regex for ticker route + `quote_plus` for topic route is validated by both reviewers
- **Test separation** — unit tests monkeypatched; integration tests under `tests/integration/`; tolerant assertions for live assertions

### Agreed Concerns
1. **yfinance version pin `>=1.3.0,<2.0` may be unsatisfiable** (Codex HIGH, Gemini LOW implied) — confirm actual available version on PyPI before execution; adjust floor to `>=1.2.2,<2.0` or whatever `uv sync` resolves
2. **RSS provider needs `response.raise_for_status()`** (Codex HIGH) — without it, 429s or error pages silently become empty-but-fresh feeds, defeating Pitfall 4 defense
3. **httpx.AsyncClient lifecycle** (Gemini LOW, Codex implied) — ensure client is created once per `get_headlines` call inside an `async with` context manager, not per-entity
4. **yfinance `.info` fetched for all three protocol methods** (Codex MEDIUM) — `get_prices` and `get_volume` pay the expensive fundamentals HTTP call unnecessarily; Phase 40 call pattern needs documentation

### Divergent Views
- **Overall risk level:** Gemini rates LOW, Codex rates MEDIUM. The difference is driven by Codex's concern about the yfinance version pin blocker and RSS status handling — both actionable before execution.
- **`asyncio.gather(return_exceptions=False)`:** Codex considers this brittle for D-19; Gemini did not raise it. Worth considering `return_exceptions=True` with explicit type-check on results (though `_fetch_one_sync` being contractually never-raise means this is defense-in-depth, not a critical gap).
- **RSS entity filter for ticker-routed feeds:** Codex raises that Yahoo RSS titles say "Apple" not "AAPL" so substring filtering may over-filter; Gemini did not flag this. D-03 is literal in the design decisions; Phase 38 accepts this for now.
