---
phase: 38
plan: 02
subsystem: ingestion
tags: [ingestion, rss, news, feedparser, httpx, protocol-implementation, url-injection-mitigation, utc-timezone-safety, explicit-timeout]
dependency_graph:
  requires:
    - alphaswarm.ingestion.providers (NewsProvider Protocol, _fetch_failed_news_slice helper — Phase 37-02)
    - alphaswarm.ingestion.types (NewsSlice — Phase 37-01)
    - feedparser>=6.0.12,<7.0 (newly added)
    - httpx>=0.28.0 (already present)
  provides:
    - RSSNewsProvider (real NewsProvider for Phase 40 ContextPacket.news)
    - _route_url helper (ticker -> Yahoo RSS; else Google News RSS with quote_plus sanitization)
    - _entry_age_hours helper (UTC-safe calendar.timegm struct_time conversion)
  affects:
    - pyproject.toml dependencies + importlinter source_modules
    - tests/invariants/test_importlinter_coverage.py (stays green with new module)
tech_stack:
  added:
    - feedparser 6.0.12 (satisfies >=6.0.12,<7.0 floor; transitive: sgmllib3k)
  patterns:
    - "httpx.AsyncClient as async-with context manager — single client shared across asyncio.gather batch for TCP connection reuse (NOT one client per entity)"
    - "Explicit timeout=_REQUEST_TIMEOUT_S on AsyncClient constructor AND per-request (REVIEWS consensus #2 — defense-in-depth)"
    - "feedparser.parse(response.text) — NEVER feedparser.parse(url) (Pitfall 2 — sync internal fetcher would trip bozo=True)"
    - "r.raise_for_status() called BEFORE feedparser.parse — 429 becomes fetch_failed, not empty-but-fresh (Codex HIGH ordering lock)"
    - "calendar.timegm(published_parsed) — UTC-safe struct_time -> epoch (REVIEWS consensus #1 — replaces local-time converter)"
    - "urllib.parse.quote_plus(entity) on Google News path — T-38-01 URL injection mitigation"
    - "Strict ticker regex ^[A-Z]{1,5}$ as whitelist — T-38-01 URL injection mitigation on Yahoo path"
    - "D-19 never-raise: one broad try/except wrapping the entire _fetch_one body; no partial catches"
    - "Pitfall 9 empty-input guard BEFORE constructing AsyncClient"
key_files:
  created:
    - src/alphaswarm/ingestion/rss_provider.py
    - tests/test_rss_provider.py
    - .planning/phases/38-market-data-news-providers/38-02-SUMMARY.md
  modified:
    - pyproject.toml
    - src/alphaswarm/ingestion/__init__.py
    - uv.lock
decisions:
  - "D-01 RSS-only news provider: no API key, no rate limits — feedparser + httpx"
  - "D-02 dual-source routing: _TICKER_RE ^[A-Z]{1,5}$ matches -> Yahoo Finance RSS; everything else -> Google News RSS search with quote_plus"
  - "D-03 case-insensitive substring entity filter: needle = entity.lower(); if needle in title.lower()"
  - "D-04 stack: feedparser (RSS parse) + httpx.AsyncClient (async fetch)"
  - "D-09 staleness binary: 'fresh' on success including 0-entry HTTP 200; 'fetch_failed' on exception"
  - "D-10 no caching: each call is a fresh scrape"
  - "D-19 never-raise: entire _fetch_one body under one broad except Exception -> _fetch_failed_news_slice(entity, 'rss')"
  - "REVIEWS consensus #1 (HIGH — Codex): calendar.timegm(published_parsed) for UTC-safe struct_time -> epoch; local-time-based stdlib converter would skew max_age_hours by local timezone offset on non-UTC hosts"
  - "REVIEWS consensus #2 (MEDIUM — Codex/Gemini): explicit timeout=_REQUEST_TIMEOUT_S on httpx.AsyncClient constructor; hanging upstream could bypass D-19 without a constructor-level timeout"
  - "Codex HIGH (already incorporated): r.raise_for_status() called BEFORE feedparser.parse(r.text) — ordering invariant locked by unit test so a 429 cannot be silently parsed as empty-but-fresh"
  - "Gemini MEDIUM (documented, intentional): international tickers with suffixes (VOD.L, SHOP.TO, 7203.T) do NOT match ^[A-Z]{1,5}$ and route to Google News RSS — documented in module docstring, locked scope per CONTEXT.md D-01/D-02"
  - "Gemini/Codex MEDIUM (reaffirmed): single httpx.AsyncClient per get_headlines call, shared across asyncio.gather — NOT one client per entity"
  - "T-38-01 URL injection (HIGH): ticker regex whitelist (^[A-Z]{1,5}$) + urllib.parse.quote_plus(entity) on Google News path; dual defenses asserted by test_url_injection_in_entity_is_quote_plus_encoded and test_ticker_regex_is_strict_uppercase_1_to_5"
metrics:
  started_at: "2026-04-18T22:33:50Z"
  completed_at: "2026-04-18T22:41:53Z"
  duration_minutes: 8
  tasks_completed: 3
  tests_added: 26
  tests_passing_in_regression: 83
---

# Phase 38 Plan 02: RSS News Provider Summary

## One-liner

Real `RSSNewsProvider` — `NewsProvider` Protocol implementation with dual-source routing (ticker `^[A-Z]{1,5}$` -> Yahoo Finance RSS; everything else -> Google News RSS with `urllib.parse.quote_plus` sanitization), `httpx.AsyncClient` async fetch with explicit `timeout=10.0` constructor (REVIEWS #2), `feedparser.parse(r.text)` after `r.raise_for_status()`, UTC-safe `calendar.timegm(published_parsed)` for `max_age_hours` filtering (REVIEWS #1), per-request `User-Agent: Mozilla/5.0 AlphaSwarm/6.0` (Pitfall 4), and D-19 never-raise contract.

## What Shipped

### Source
- `src/alphaswarm/ingestion/rss_provider.py` (new, ~180 lines)
  - `_SOURCE = "rss"`, `_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"`, `_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")`, `_REQUEST_TIMEOUT_S = 10.0` module constants
  - `_route_url(entity)` — ticker -> Yahoo Finance RSS; else Google News RSS with `quote_plus(entity)` percent-encoding (T-38-01)
  - `_entry_age_hours(entry)` — UTC-safe `calendar.timegm(published_parsed)` conversion (REVIEWS #1); returns `None` for undated entries
  - `_fetch_one(client, entity, max_age_hours)` — never-raise coroutine wrapping the full body in one broad `try/except Exception` (D-19). Inside: `_route_url(entity)` -> `client.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT_S)` -> `r.raise_for_status()` -> `feedparser.parse(r.text)` -> entity substring filter (D-03) -> `max_age_hours` filter (Pitfall 3 + REVIEWS #1) -> `NewsSlice(..., staleness="fresh")`. On any exception: `_fetch_failed_news_slice(entity, _SOURCE)` (Pattern 3 reuse).
  - `class RSSNewsProvider.get_headlines(entities, *, max_age_hours=72)` — empty input guard (Pitfall 9); `async with httpx.AsyncClient(follow_redirects=True, timeout=_REQUEST_TIMEOUT_S)` — **explicit constructor timeout is the REVIEWS #2 fix** — shared client across `asyncio.gather` batch; duplicate entities collapse to single dict key
  - Full-module docstring covers D-01/D-02/D-03/D-04/D-09/D-10/D-19, Pitfalls 2/3/4, T-38-01, REVIEWS consensus #1 + #2, international-ticker routing note (Gemini MEDIUM — intentional scope)

### Tests
- `tests/test_rss_provider.py` (new, 26 tests, ~590 lines)
  - **URL routing + T-38-01 (4 tests):** ticker vs topic; URL injection quote_plus encoding (`EV&cmd=drop` -> `EV%26cmd%3Ddrop`); 6-char uppercase rejected by ticker regex; lowercase non-ticker routes to Google News
  - **Pitfall 4 User-Agent (1 test):** every recorded `get()` call has `User-Agent: Mozilla/5.0 AlphaSwarm/6.0`
  - **REVIEWS consensus #2 runtime (1 test):** `_MockAsyncClient.init_kwargs_log` recorded `timeout=10.0` and `follow_redirects=True`
  - **Entity filter + max_age_hours (4 tests):** case-insensitive substring (apple/TESLA); three-entry age filter (1h, 50h, 200h with max_age_hours=72 vs 24); 6h UTC entry passes max_age_hours=12 (REVIEWS #1 behavioral guard); undated entry passes age filter
  - **D-19 never-raise (4 tests):** httpx.ConnectError -> fetch_failed; HTTP 429 raise_for_status -> fetch_failed (Pitfall 4 regression); httpx.ReadTimeout -> fetch_failed (defense-in-depth); 0-entries HTTP 200 -> fresh (Research Open Q 2)
  - **Pitfall 9 + duplicate (2 tests):** empty list returns `{}` without constructing `_ForbidConstructionClient`; `["AAPL", "AAPL", "AAPL"]` collapses to `{"AAPL"}` key
  - **Protocol conformance (2 tests):** `inspect.iscoroutinefunction(provider.get_headlines)`; `_news_consumer(p: NewsProvider)` structural probe
  - **Module-level grep meta invariants (8 tests):**
    - imports httpx + feedparser; NOT yfinance
    - uses `_fetch_failed_news_slice` helper (Pattern 3)
    - `_TICKER_RE` literal `r"^[A-Z]{1,5}$"` present (T-38-01)
    - `feedparser.parse(r.text)` present; `feedparser.parse(url)` absent (Pitfall 2)
    - `r.raise_for_status()` offset < `feedparser.parse(r.text)` offset (Codex HIGH ordering lock)
    - `import calendar` + `calendar.timegm(published_parsed)` present; `time.mktime` absent (REVIEWS #1 grep invariant)
    - `httpx.AsyncClient(` block contains `timeout=_REQUEST_TIMEOUT_S` within 4 lines (REVIEWS #2 grep invariant)

### Config
- `pyproject.toml` `[project].dependencies`: `"feedparser>=6.0.12,<7.0"` appended AFTER `"yfinance>=1.2.2,<2.0"` (Plan 01 ordering preserved)
- `pyproject.toml` `[tool.importlinter].contracts[0].source_modules`: `"alphaswarm.ingestion.rss_provider"` inserted between `"alphaswarm.ingestion.yfinance_provider"` and `"alphaswarm.interview"` (same commit as module creation — Pitfall 8 drift-resistance preserved)
- `src/alphaswarm/ingestion/__init__.py`: re-exports `RSSNewsProvider`; `__all__` kept alphabetical (slot between `"NewsSlice"` and `"StalenessState"` that Plan 01 reserved)

## Decisions Implemented

| Decision | Realization |
|----------|-------------|
| D-01 RSS-only, no API key | Only two feeds used: `finance.yahoo.com/rss/headline?s=...` and `news.google.com/rss/search?q=...` |
| D-02 dual-source routing | `_route_url(entity)`: `_TICKER_RE.match(entity)` -> Yahoo; else Google News with `quote_plus(entity)` |
| D-03 case-insensitive substring filter | `needle = entity.lower(); if needle in title.lower(): keep` |
| D-04 stack | `import httpx` + `import feedparser` — no requests, no aiohttp |
| D-09 fresh/fetch_failed binary | `staleness="fresh"` on success (even with 0 entries); `_fetch_failed_news_slice` (-> `staleness="fetch_failed"`) on any exception |
| D-10 no caching | Every call constructs a fresh `httpx.AsyncClient`; no client retained between calls |
| D-19 never-raise | Full `_fetch_one` body under one `try: ... except Exception: return _fetch_failed_news_slice(entity, _SOURCE)` |

## Review Fixes Applied

| Review | Severity | Fix |
|--------|----------|-----|
| **Codex consensus #1** — Timezone skew in `max_age_hours` via wrong struct_time converter | **HIGH** | `_entry_age_hours` uses `calendar.timegm(published_parsed)` which treats the struct as UTC (RSS/Atom spec). The local-time-based stdlib converter would skew by ~7-8h on America/Los_Angeles hosts. Verified by `test_max_age_hours_uses_calendar_timegm_not_local_time` (behavioral: 6h-old entry passes max_age_hours=12) + `test_rss_provider_uses_calendar_timegm_not_time_mktime` (grep invariant forbidding `time.mktime` substring). |
| **Codex/Gemini consensus #2** — `httpx.AsyncClient(follow_redirects=True)` without explicit timeout can hang indefinitely | **MEDIUM** | Constructor called with `timeout=_REQUEST_TIMEOUT_S` (10.0). Per-request `timeout=` retained for defense-in-depth. Verified by `test_httpx_asyncclient_constructed_with_explicit_timeout` (runtime: `init_kwargs_log[0]["timeout"] == 10.0`) + `test_rss_provider_asyncclient_has_explicit_timeout_kwarg` (grep invariant). |
| **Codex HIGH** — `r.raise_for_status()` ordering | HIGH | `raise_for_status()` called BEFORE `feedparser.parse(r.text)` so a Yahoo 429 or Google error HTML page becomes `fetch_failed` (via D-19) rather than being silently parsed as empty-but-fresh. Verified by `test_http_429_raises_for_status_and_returns_fetch_failed` (behavioral) + `test_rss_provider_raises_for_status_before_parse` (grep invariant: `i_status < i_parse`). |
| **Gemini MEDIUM — International ticker routing** | documented, intentional | Module docstring explicitly documents that `VOD.L`, `SHOP.TO`, `7203.T` do NOT match `^[A-Z]{1,5}$` and route to Google News RSS — this is locked scope per CONTEXT.md D-01/D-02, NOT a bug. If broader Yahoo RSS international coverage becomes a requirement, regex can relax to `^[A-Z]{1,5}(\\.[A-Z]{1,2})?$` in a later phase. |
| **Gemini/Codex MEDIUM — Single shared AsyncClient per batch** | reaffirmed | `async with httpx.AsyncClient(...) as client:` wraps the entire `asyncio.gather(...)` call — one client, many concurrent entities, TCP connection reuse. Explicit `async with` guarantees close on `__aexit__`. |

## Threat Mitigations

| Threat | Disposition | How |
|--------|-------------|-----|
| T-38-01 URL injection via entity string | mitigate | Ticker path: strict `^[A-Z]{1,5}$` regex whitelist — no URL-reserved chars can reach Yahoo URL. Google News path: `urllib.parse.quote_plus(entity)` percent-encodes `& = ? / ` and all reserved chars. Verified by `test_url_injection_in_entity_is_quote_plus_encoded` + `test_ticker_regex_is_strict_uppercase_1_to_5`. |
| T-38-03 DoS via malformed feed | mitigate | feedparser sets `bozo=True` rather than raising; any attribute error from bozo entries caught by the outer `except Exception`. D-19 contract holds. Verified by `test_get_headlines_fetch_failed_on_exception`. |
| T-38-04 DoS via hanging upstream | mitigate | REVIEWS #2 — constructor `timeout=10.0`; per-request `timeout=10.0` — any hang >10s raises `ReadTimeout`/`ConnectTimeout` which D-19 converts to `fetch_failed`. Verified by `test_httpx_asyncclient_constructed_with_explicit_timeout`, `test_httpx_timeout_exception_returns_fetch_failed`, `test_rss_provider_asyncclient_has_explicit_timeout_kwarg`. |
| T-38-06 Timezone skew in max_age_hours | mitigate | REVIEWS #1 — `calendar.timegm(published_parsed)` treats struct as UTC. `time.mktime` forbidden at source. Verified by `test_max_age_hours_uses_calendar_timegm_not_local_time` + `test_rss_provider_uses_calendar_timegm_not_time_mktime`. |
| T-38-10 Event-loop block from sync feedparser fetch | mitigate | `feedparser.parse(r.text)` — never passed a URL. Grep invariant `test_rss_provider_never_parses_url_directly` locks this. |
| T-38-11 Yahoo 429 rate-limit ban | mitigate | `User-Agent: Mozilla/5.0 AlphaSwarm/6.0` on every request. Verified by `test_user_agent_header_is_sent_on_every_request` (3 entities -> 3 recorded calls, all with UA). |
| T-38-14 Supply-chain (feedparser tampering) | mitigate | Pin `feedparser>=6.0.12,<7.0`; reproducibility via `uv.lock`. |
| T-38-15 importlinter whitelist drift | mitigate | `alphaswarm.ingestion.rss_provider` added to `source_modules` in the same commit as the module file creation (Task 1). `tests/invariants/test_importlinter_coverage.py` drift test would fail if not. |

## Pitfalls Mitigated

| Pitfall | Mitigation | Verified By |
|---------|-----------|-------------|
| 2 — feedparser sync internal fetcher | `feedparser.parse(r.text)` only; grep invariant forbids URL form | `test_rss_provider_never_parses_url_directly` |
| 3 — published_parsed struct_time misinterpreted | `_entry_age_hours` uses `calendar.timegm(published_parsed)` + `datetime.fromtimestamp(ts, tz=UTC)` | `test_max_age_hours_filter`, `test_max_age_hours_uses_calendar_timegm_not_local_time` |
| 4 — Yahoo 429 without User-Agent | Every request sends `User-Agent: Mozilla/5.0 AlphaSwarm/6.0` | `test_user_agent_header_is_sent_on_every_request`, `test_http_429_raises_for_status_and_returns_fetch_failed` |
| 7 — Unit tests hitting real network | Every test monkeypatches `alphaswarm.ingestion.rss_provider.httpx.AsyncClient`; pytest-socket `--disable-socket` is the global second line of defense | All 26 tests pass under `--disable-socket` |
| 8 — importlinter source_modules drift | Task 1 adds `alphaswarm.ingestion.rss_provider` in the same commit as the module | `tests/invariants/test_importlinter_coverage.py` — 3/3 pass |
| 9 — `asyncio.gather(*empty)` footgun | `if not entities: return {}` guard before any `httpx.AsyncClient` construction | `test_empty_entity_list_returns_empty_dict` (uses `_ForbidConstructionClient` that raises in `__init__`) |

## Requirements Satisfied

- **INGEST-02**: Real `RSSNewsProvider` implements `NewsProvider` Protocol with batch-first async signature; returns `dict[str, NewsSlice]` where each `NewsSlice` has `entity: str`, `headlines: tuple[str, ...]` (entity-filtered + age-filtered), `source="rss"`, `staleness="fresh"` on success / `"fetch_failed"` on exception.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] feedparser has no type stubs / py.typed marker**
- **Found during:** Task 2 (first mypy run against the implementation)
- **Issue:** `uv run mypy src/alphaswarm/ingestion/rss_provider.py` failed with `error: Skipping analyzing "feedparser": module is installed, but missing library stubs or py.typed marker [import-untyped]`. mypy strict treats this as an error.
- **Fix:** Added `# type: ignore[import-untyped]` to the `import feedparser` line — same pattern used for `yfinance` in Plan 38-01 (precedent established). Localized escape; does not weaken type coverage anywhere else in the module.
- **Files modified:** `src/alphaswarm/ingestion/rss_provider.py`
- **Commit:** c9d925c (Task 2)

**2. [Rule 3 - Blocking] Module docstring contained banned substrings that unit tests forbid**
- **Found during:** Task 2 grep-invariant check (pre-commit)
- **Issue:** The initial docstring (as written in the plan) contained the literal strings `feedparser.parse(url)` and `time.mktime` as documentation references. Task 3's grep invariants `test_rss_provider_never_parses_url_directly` and `test_rss_provider_uses_calendar_timegm_not_time_mktime` forbid those substrings anywhere in the source file.
- **Fix:** Reworded two docstring sections to describe the anti-patterns without using the literal forbidden tokens — e.g., "passing a URL directly to feedparser uses its sync internal fetcher" instead of "feedparser.parse(url) uses a sync URL fetcher", and "the local-time-based stdlib converter" instead of "time.mktime". Semantics preserved.
- **Files modified:** `src/alphaswarm/ingestion/rss_provider.py`
- **Commit:** c9d925c (Task 2)

**3. [Rule 3 - Blocking] Test file mypy strict `[no-any-return]` in `_MockAsyncClient.get`**
- **Found during:** Task 3 mypy verification
- **Issue:** `_MockAsyncClient.responder` is typed `Any` (callable | dict | None). Even though the callable branch calls `responder(url)` and assigns to `maybe`, mypy cannot narrow the `Any` return back to `_MockResponse`, producing `Returning Any from function declared to return "_MockResponse"` errors on the two return sites.
- **Fix:** Added `assert isinstance(maybe, _MockResponse)` and `assert isinstance(resp, _MockResponse)` runtime narrows right before each return. These are no-op assertions in the happy path (the mock is constructed to return `_MockResponse` instances) and give mypy the narrowing hint. Does not weaken test semantics.
- **Files modified:** `tests/test_rss_provider.py`
- **Commit:** db67cf7 (Task 3)

**4. [Rule 3 - Blocking] ruff E501 line-too-long on `_ForbidConstructionClient` AssertionError string**
- **Found during:** Task 3 ruff verification
- **Issue:** The assertion message (101 chars) exceeded ruff's line-length 100 config.
- **Fix:** Wrapped the string onto two concatenated literals — semantics identical.
- **Files modified:** `tests/test_rss_provider.py`
- **Commit:** db67cf7 (Task 3)

**5. [Tooling] ruff auto-fixes (I001 + UP037) on `tests/test_rss_provider.py`**
- **Found during:** Task 3 ruff verification
- **Issue:** Initial ruff check flagged two issues: I001 import-ordering spacing and UP037 unnecessary string quotes on the `_MockAsyncClient.__aenter__` forward reference.
- **Fix:** `uv run ruff check tests/test_rss_provider.py --fix` auto-resolved both: blank line inserted after `from __future__ import annotations`; forward reference unquoted to `_MockAsyncClient` directly (valid with `from __future__ import annotations`).
- **Files modified:** `tests/test_rss_provider.py`
- **Commit:** db67cf7 (includes the ruff-fixed form)

No architectural deviations (Rule 4). No scope boundary violations; no out-of-scope fixes.

## How to Verify

```bash
uv run pytest tests/test_rss_provider.py -v                                                              # 26 tests PASSED
uv run pytest tests/test_providers.py tests/test_yfinance_provider.py tests/test_rss_provider.py tests/invariants/ -x -q  # 83 PASSED
uv run mypy src/alphaswarm/ingestion/rss_provider.py tests/test_rss_provider.py                          # Success: no issues found in 2 source files
uv run ruff check src/alphaswarm/ingestion/rss_provider.py tests/test_rss_provider.py                    # All checks passed!
uv run lint-imports                                                                                       # Contracts: 1 kept, 0 broken.
uv run python -c "from alphaswarm.ingestion import RSSNewsProvider; print('ok')"                          # ok

# REVIEWS consensus invariants (source-level)
grep -q "calendar.timegm(published_parsed)" src/alphaswarm/ingestion/rss_provider.py                     # REVIEWS #1 positive
! grep -q "time.mktime" src/alphaswarm/ingestion/rss_provider.py                                          # REVIEWS #1 negative
grep -A 3 "httpx.AsyncClient(" src/alphaswarm/ingestion/rss_provider.py | grep -q "timeout=_REQUEST_TIMEOUT_S"  # REVIEWS #2
```

## Unblocks

- **Plan 38-03** (integration tests) — can now import `RSSNewsProvider` and exercise it under `pytest.mark.enable_socket` against real Yahoo Finance RSS + Google News RSS.
- **Phase 40** (ContextPacket assembly) — has a real `NewsProvider` to wire into `ContextPacket.news`.

## Self-Check: PASSED

- `src/alphaswarm/ingestion/rss_provider.py` — FOUND
- `tests/test_rss_provider.py` — FOUND
- `.planning/phases/38-market-data-news-providers/38-02-SUMMARY.md` — FOUND (this file)
- Commit `032c8cf` (Task 1) — FOUND in `git log`
- Commit `c9d925c` (Task 2) — FOUND in `git log`
- Commit `db67cf7` (Task 3) — FOUND in `git log`
- `RSSNewsProvider` importable — verified at runtime (`from alphaswarm.ingestion import RSSNewsProvider`)
- 26/26 unit tests PASSED under pytest-socket `--disable-socket`
- 83/83 regression suite PASSED (test_providers + test_yfinance_provider + test_rss_provider + invariants)
- mypy strict on provider + test file: Success (2 source files)
- ruff on provider + test file: All checks passed
- importlinter contract KEPT, coverage invariant green (3/3 tests pass)
- REVIEWS #1 source invariants: `calendar.timegm(published_parsed)` present, `time.mktime` absent
- REVIEWS #2 source invariant: `timeout=_REQUEST_TIMEOUT_S` within `httpx.AsyncClient(` block
