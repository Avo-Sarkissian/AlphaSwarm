---
phase: 38
auditor: gsd-security-auditor
asvs_level: L1
block_on: HIGH
audited_at: 2026-04-18
result: SECURED
threats_total: 18
threats_closed: 18
threats_open: 0
unregistered_flags: 0
---

# Phase 38 Security Audit

## Result: SECURED

**Phase:** 38 — Market Data & News Providers
**Threats Closed:** 18/18
**ASVS Level:** L1
**Block-on:** HIGH

---

## Threat Verification

### Plan 38-01 Threats (YFinanceMarketDataProvider)

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-38-03 | Denial of Service (aggregation loop crash) | mitigate | CLOSED | `except Exception:` at `yfinance_provider.py:112`; returns `_fetch_failed_market_slice(ticker, _SOURCE)`. Tests `test_get_prices_fetch_failed_on_exception` and `test_get_prices_generic_exception_returns_fetch_failed` present in `tests/test_yfinance_provider.py:276-301`. |
| T-38-04 | Denial of Service (event-loop block) | mitigate | CLOSED | `asyncio.to_thread(_fetch_one_sync, t)` at `yfinance_provider.py:128`. All `yf.Ticker`, `.fast_info`, and `.info` accesses occur inside the synchronous `_fetch_one_sync` function that is dispatched via `asyncio.to_thread`. |
| T-38-05 | Integrity (financial precision) | mitigate | CLOSED | `_decimal_or_none` returns `Decimal(str(value))` at `yfinance_provider.py:81`. No bare `Decimal(float)` construction present. Test `test_decimal_precision_not_float` at `test_yfinance_provider.py:192`. |
| T-38-05b | Integrity (NaN/Inf leakage) | mitigate | CLOSED | `isinstance(value, float) and (math.isnan(value) or math.isinf(value))` guard at `yfinance_provider.py:79`. Tests `test_decimal_or_none_unit`, `test_nan_trailing_pe_is_guarded_to_none`, `test_inf_fundamentals_are_guarded_to_none`, and `test_yfinance_provider_module_guards_nan_inf` present. |
| T-38-06 | Supply-chain (yfinance package) | mitigate | CLOSED | `"yfinance>=1.2.2,<2.0"` at `pyproject.toml:20`. `uv.lock` provides hash-pinned reproducibility. |
| T-38-07 | Tampering (importlinter drift) | mitigate | CLOSED | `"alphaswarm.ingestion.yfinance_provider"` at `pyproject.toml:79`. Drift invariant test `test_source_modules_covers_every_actual_package` in `tests/invariants/test_importlinter_coverage.py` (confirmed green in 38-01-SUMMARY.md). |
| T-38-08 | Information Disclosure (log secrets) | accept | CLOSED | Documented: yfinance uses no API keys; Phase 37 ISOL-04 PII redaction in shared_processors chain. No secrets can leak. Accepted per plan. |
| T-38-09 | Spoofing (Yahoo shape change) | accept | CLOSED | Documented: missing yfinance fields return `None` from `info.get(...)`; integration tests detect content degradation via `staleness='fresh'` + Decimal assertions. Accepted per plan. |

### Plan 38-02 Threats (RSSNewsProvider)

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-38-01 | Tampering (URL injection) | mitigate | CLOSED | Ticker path: `_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")` at `rss_provider.py:73`; Google News path: `quote_plus(entity)` at `rss_provider.py:85`. Tests `test_url_injection_in_entity_is_quote_plus_encoded` and `test_ticker_regex_is_strict_uppercase_1_to_5` in `tests/test_rss_provider.py:160-189`. |
| T-38-02 | Tampering (prompt injection — Phase 40 seed) | accept | CLOSED | Out of scope for Phase 38 per plan. Phase 40 must sanitize. Accepted per plan. |
| T-38-03b | Denial of Service (malformed feed) | mitigate | CLOSED | `except Exception:` at `rss_provider.py:150`; feedparser `bozo=True` on malformed input propagates attribute errors caught by broad except. Test `test_get_headlines_fetch_failed_on_exception` at `test_rss_provider.py:372`. |
| T-38-04b | Denial of Service (hanging upstream) | mitigate | CLOSED | `timeout=_REQUEST_TIMEOUT_S` (10.0) on `httpx.AsyncClient` constructor at `rss_provider.py:174`; per-request `timeout=_REQUEST_TIMEOUT_S` at `rss_provider.py:127`. Tests `test_httpx_asyncclient_constructed_with_explicit_timeout`, `test_httpx_timeout_exception_returns_fetch_failed`, `test_rss_provider_asyncclient_has_explicit_timeout_kwarg` present. |
| T-38-06b | Tampering (timezone skew) | mitigate | CLOSED | `calendar.timegm(published_parsed)` at `rss_provider.py:104`. `time.mktime` absent from `rss_provider.py` (confirmed by `test_rss_provider_uses_calendar_timegm_not_time_mktime`). Tests `test_max_age_hours_uses_calendar_timegm_not_local_time` and grep invariant present. |
| T-38-10 | Denial of Service (sync feedparser fetch) | mitigate | CLOSED | `feedparser.parse(r.text)` at `rss_provider.py:130`. URL string never passed to feedparser. Grep invariant `test_rss_provider_never_parses_url_directly` in `test_rss_provider.py:521`. |
| T-38-11 | Denial of Service (Yahoo 429) | mitigate | CLOSED | `_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"` at `rss_provider.py:72`; header applied at `rss_provider.py:126`. Test `test_user_agent_header_is_sent_on_every_request` at `test_rss_provider.py:209`. |
| T-38-12 | Information Disclosure (SSRF) | accept | CLOSED | Hard-coded hostnames `finance.yahoo.com` and `news.google.com`; entity only reaches path/query via `quote_plus`. Accepted per plan. |
| T-38-13 | Denial of Service (XML bomb) | accept | CLOSED | feedparser 6.0.12 hardened parser; `feedparser>=6.0.12,<7.0` pin at `pyproject.toml:21`. Accepted per plan. |
| T-38-14 | Supply-chain (feedparser) | mitigate | CLOSED | `"feedparser>=6.0.12,<7.0"` at `pyproject.toml:21`. `uv.lock` provides hash-pinned reproducibility. |
| T-38-15 | Tampering (importlinter drift for rss_provider) | mitigate | CLOSED | `"alphaswarm.ingestion.rss_provider"` at `pyproject.toml:80`. Drift invariant test confirmed green in 38-02-SUMMARY.md. |

### Plan 38-03 Threats (Integration Tests)

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-38-11 (asserted) | DoS (Yahoo 429) real-network guard | mitigate | CLOSED | `test_rss_real_user_agent_prevents_yahoo_429` at `tests/integration/test_rss_provider_live.py:93`. Test passed against real Yahoo in 38-03-SUMMARY.md. |
| T-38-16 | DoS (CI flakiness) | accept | CLOSED | Shape-only assertions (staleness='fresh', price > 0); tolerant delisted-ticker assertion accepts fetch_failed OR valid-empty-slice. Accepted per plan with documented residual risk. |
| T-38-17 | Tampering (test bypasses socket gate) | mitigate | CLOSED | Both integration test modules live under `tests/integration/`; `test_test_module_lives_under_tests_integration` self-check at `test_yfinance_provider_live.py:136` and `test_rss_provider_live.py:119`. |
| T-38-18 | Information Disclosure (secrets in logs) | mitigate | CLOSED | No API keys used by either provider; Phase 37 ISOL-04 PII redaction in effect for provider-side logging. Confirmed in 38-03-SUMMARY.md. |

---

## Accepted Risks Log

| Threat ID | Risk | Rationale | Owner |
|-----------|------|-----------|-------|
| T-38-08 | Information Disclosure — log secrets | yfinance requires no API keys; no secrets exist to leak. Phase 37 ISOL-04 shared_processors chain provides PII redaction. | Phase 37 |
| T-38-09 | Spoofing — Yahoo response shape change | Missing fields return None via `info.get(...)`; integration tests detect degradation via staleness + shape assertions. yfinance pin `<2.0` provides upstream patch delivery. | yfinance maintainers |
| T-38-02 | Tampering — prompt injection in Phase 40 seed | Out of scope for Phase 38. Phase 40 orchestrator is explicitly responsible for sanitizing entity strings before calling `RSSNewsProvider.get_headlines`. | Phase 40 |
| T-38-12 | Information Disclosure — SSRF | Hostnames hard-coded (`finance.yahoo.com`, `news.google.com`); entity string only reaches URL path/query through `quote_plus`. No redirect-based SSRF vector beyond hard-coded domains (follow_redirects=True scoped to same domains). | Accepted at L1 |
| T-38-13 | Denial of Service — XML bomb | feedparser 6.0.12+ uses a hardened parser that does not expand entity references. Pin `feedparser>=6.0.12,<7.0` prevents downgrade to vulnerable versions. | feedparser maintainers |
| T-38-16 | DoS — CI flakiness from real-network tests | Tolerant shape assertions limit false positives; real failures indicate genuine upstream degradation. Integration tests can be gated behind a slow marker if CI friction accumulates. | Phase 38 |

---

## Unregistered Flags

None. No `## Threat Flags` section was present in 38-01-SUMMARY.md, 38-02-SUMMARY.md, or 38-03-SUMMARY.md. Executors did not surface new attack surface beyond the registered threat register.

---

## Key Mitigation Evidence Summary

### Source-Level Patterns Verified

| Pattern | Location | Threat(s) |
|---------|----------|-----------|
| `except Exception:` broad try/except in `_fetch_one_sync` | `yfinance_provider.py:112` | T-38-03 |
| `asyncio.to_thread(_fetch_one_sync, t)` | `yfinance_provider.py:128` | T-38-04 |
| `math.isnan(value) or math.isinf(value)` in `_decimal_or_none` | `yfinance_provider.py:79` | T-38-05b |
| `Decimal(str(value))` — no bare `Decimal(float)` | `yfinance_provider.py:81` | T-38-05 |
| `"yfinance>=1.2.2,<2.0"` in dependencies | `pyproject.toml:20` | T-38-06 |
| `"alphaswarm.ingestion.yfinance_provider"` in source_modules | `pyproject.toml:79` | T-38-07 |
| `_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")` | `rss_provider.py:73` | T-38-01 |
| `quote_plus(entity)` in Google News URL | `rss_provider.py:85` | T-38-01 |
| `except Exception:` broad try/except in `_fetch_one` | `rss_provider.py:150` | T-38-03b |
| `timeout=_REQUEST_TIMEOUT_S` on AsyncClient constructor | `rss_provider.py:174` | T-38-04b |
| `timeout=_REQUEST_TIMEOUT_S` per-request | `rss_provider.py:127` | T-38-04b |
| `r.raise_for_status()` before `feedparser.parse(r.text)` | `rss_provider.py:129-130` | T-38-03b, T-38-11 |
| `calendar.timegm(published_parsed)` — no `time.mktime` | `rss_provider.py:104` | T-38-06b |
| `feedparser.parse(r.text)` — no URL form | `rss_provider.py:130` | T-38-10 |
| `_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"` on every request | `rss_provider.py:72, 126` | T-38-11 |
| `"feedparser>=6.0.12,<7.0"` in dependencies | `pyproject.toml:21` | T-38-14 |
| `"alphaswarm.ingestion.rss_provider"` in source_modules | `pyproject.toml:80` | T-38-15 |
| `test_test_module_lives_under_tests_integration` self-check | `tests/integration/test_yfinance_provider_live.py:136`, `tests/integration/test_rss_provider_live.py:119` | T-38-17 |
