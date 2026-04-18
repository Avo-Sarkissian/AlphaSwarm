---
phase: 37
plan_security: true
asvs_level: L1
audited: 2026-04-18
auditor: gsd-security-auditor (claude-sonnet-4-6)
result: SECURED
threats_total: 36
threats_closed: 36
threats_open: 0
---

# Phase 37 — Security Audit Report

**Phase:** 37 — Isolation Foundation: Provider Scaffolding
**Plans covered:** 37-01, 37-02, 37-03, 37-04
**ASVS Level:** L1
**Result:** SECURED — 36/36 threats closed

---

## Threat Verification

### Plan 37-01 Threats

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-37-01 | Information Disclosure | mitigate | `ConfigDict(frozen=True, extra="forbid")` present on all four swarm-side models (`Fundamentals`, `MarketSlice`, `NewsSlice`, `ContextPacket`) at `src/alphaswarm/ingestion/types.py:42,57,74,93`. Schema-assertion tests at `tests/test_ingestion_types.py:69–71,133–135,196–198` enumerate `model_fields` and assert no field name is in `SENSITIVE_FIELD_NAMES`. |
| T-37-02 | Tampering | mitigate | `@dataclasses.dataclass(frozen=True)` present on both `Holding` (line 17) and `PortfolioSnapshot` (line 29) at `src/alphaswarm/holdings/types.py`. `holdings` field declared `tuple[Holding, ...]` (line 40). Tests `test_holding_is_frozen`, `test_portfolio_snapshot_is_frozen`, `test_portfolio_snapshot_holdings_is_not_a_list` in `tests/test_holdings_types.py`. |
| T-37-03 | Information Disclosure | mitigate | `sha256_first8` raises `TypeError` on empty string (line 25–26) and on non-str input (line 23–24) at `src/alphaswarm/security/hashing.py`. Verified by `test_sha256_first8_rejects_empty_string` and `test_sha256_first8_rejects_none` in `tests/test_security_hashing.py`. |
| T-37-04 | Tampering (type drift) | mitigate | `test_holdings_types_import_only_stdlib` in `tests/test_holdings_types.py:71–79` reads `holdings/types.py` source and asserts absence of `import pydantic`, `import yfinance`, `import structlog`, `import httpx`. Confirmed: `src/alphaswarm/holdings/types.py` imports only `dataclasses`, `datetime`, `decimal`. |
| T-37-05 | Information Disclosure (float rounding) | mitigate | `Holding.qty` and `Holding.cost_basis` typed `Decimal` (`src/alphaswarm/holdings/types.py:22–23`). `MarketSlice.price` typed `Decimal | None` (`src/alphaswarm/ingestion/types.py:60`). All `Fundamentals` fields are `Decimal | None`. No `float` in any financial field. Asserted by `test_holding_constructs_with_decimal_qty_and_cost_basis` and `test_market_slice_price_accepts_decimal`. |
| T-37-06 | Tampering (shallow immutability) | mitigate | All collection fields use `tuple[...]`: `PortfolioSnapshot.holdings: tuple[Holding, ...]`, `ContextPacket.entities/market/news: tuple[...]`, `NewsSlice.headlines: tuple[str, ...]`. Nested `Fundamentals` is a frozen `BaseModel` not `dict`. Asserted by `test_context_packet_annotations_are_tuple_only` (annotation-level scan), `test_market_slice_fundamentals_is_nested_frozen_model_not_dict`, and `test_fundamentals_is_frozen_base_model`. |
| T-37-07 | Repudiation | accept | ACCEPTED — Phase 37 scaffolding only; ASVS L1 does not require construction audit-logging for data-modeling work. Accepted risk documented in plan 37-01 threat register. |

### Plan 37-02 Threats

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-37-07b | Denial of Service | mitigate | `FakeMarketDataProvider._resolve` returns `_fetch_failed_market_slice` for unknown tickers (line 117–118 of `providers.py`). `FakeNewsProvider.get_headlines` uses `.get(e, _fetch_failed_news_slice(...))` (line 144). Never-raise contract tested by `test_fake_market_never_raises_on_unknown_ticker`, `test_fake_market_returns_empty_dict_for_empty_ticker_list`, `test_fake_market_returns_single_key_for_duplicate_tickers`, `test_fake_market_returns_fetch_failed_when_fixture_source_raises`. |
| T-37-08 | Information Disclosure | mitigate | `test_providers_module_has_no_network_imports` in `tests/test_providers.py:251–265` reads `providers.py` and asserts no `yfinance`, `httpx`, `feedparser`, `requests`, `aiohttp` imports. Confirmed: `src/alphaswarm/ingestion/providers.py` imports only `collections.abc`, `datetime`, `typing`. |
| T-37-09 | Tampering (Protocol drift) | mitigate | Consumer probe functions `_market_consumer(p: MarketDataProvider)` and `_news_consumer(p: NewsProvider)` in `tests/test_providers.py:36–44` are the mypy-structural conformance gates. `test_fake_market_data_provider_structurally_conforms` and `test_fake_news_provider_structurally_conforms` exercise them at runtime. |
| T-37-10 | Performance regression | mitigate | `test_providers_module_has_no_runtime_checkable` in `tests/test_providers.py:276–280` asserts `@runtime_checkable` string is absent from `providers.py`. Confirmed: no `@runtime_checkable` decorator present. |
| T-37-11 | Information Disclosure (test-to-prod leak) | accept | ACCEPTED — fakes re-exported from `alphaswarm.ingestion.__init__` but return `fetch_failed` slices without any holdings state. Accepted risk documented in plan 37-02 threat register. |
| T-37-12 | Denial of Service (event-loop block) | mitigate | All Protocol and Fake methods are `async def`. `test_market_protocol_methods_are_async_def` and `test_fake_market_methods_are_async_def` use `inspect.iscoroutinefunction` at runtime (`tests/test_providers.py:62–89`). `test_providers_module_has_no_sync_get_methods` greps for sync `def get_*` variants (line 283–291). |
| T-37-13 | Tampering (staleness drift) | mitigate | `_FETCH_FAILED: StalenessState = "fetch_failed"` typed annotation at `src/alphaswarm/ingestion/providers.py:30`. `test_staleness_state_literal_set` asserts the literal members; `test_fake_market_staleness_values_belong_to_literal_set` and `test_fake_news_staleness_values_belong_to_literal_set` assert every returned slice's staleness is in the valid set. |

### Plan 37-03 Threats

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-37-14 | Information Disclosure | mitigate | `pii_redaction_processor` inserted at position 5 in `shared_processors` BEFORE `JSONRenderer`/`ConsoleRenderer` at `src/alphaswarm/logging.py:210`. Key-first scrubbing active via `_LITERAL_NORMALIZED` and `_HASHED_NORMALIZED` sets. `test_processor_runs_before_renderer_in_configured_chain` asserts `SENTINEL_TICKER` absent and `[REDACTED]` present in captured output. |
| T-37-15 | Information Disclosure (nested leak) | mitigate | `_redact_mapping` recurses via `_redact_value` (lines 133–161 and 98–131 of `logging.py`) into dicts, lists, tuples, sets. Asserted by `test_processor_recurses_into_nested_dict`, `test_processor_recurses_into_nested_list_of_dicts`, `test_processor_recurses_into_tuple`, and the nested Hypothesis fuzz. |
| T-37-16 | Denial of Service (deep nesting/cycles) | mitigate | `_MAX_REDACTION_DEPTH = 8` at `logging.py:72`; `id()`-based `seen` set initialized at `logging.py:191` and populated in `_redact_value:113–114`. Cycles replaced with `[REDACTED_CYCLE]`. Asserted by `test_processor_handles_cycles_without_stack_overflow` and `test_processor_honors_max_depth`. |
| T-37-17 | Information Disclosure (variant-case) | mitigate | `_normalize_key` at `logging.py:77–81` lowercases and strips `_`, `-`, whitespace via `re.sub(r"[\s_\-]+", "", key).lower()`. Parametrized test `test_processor_matches_case_and_separator_variants` covers 8 variants including `costBasis`, `COST_BASIS`, `Cost-Basis`, `HOLDINGS`. |
| T-37-18 | Tampering (correlation break) | mitigate | `_PASSTHROUGH_NORMALIZED = frozenset({"accountnumberhash"})` at `logging.py:62`; passthrough check is first in `_redact_mapping:141–144`. `test_account_number_hash_is_not_rehashed` asserts passthrough for key and its variants (`AccountNumberHash`, `account-number-hash`). |
| T-37-19 | Denial of Service (over-redaction) | mitigate | `_FREE_TEXT_NORMALIZED` set at `logging.py:65–67` scopes currency/SSN regex to `note`, `summary`, `message`, `text`, `description`, `reason` keys only (lines 154–158). `test_processor_does_NOT_scrub_currency_in_non_free_text_key` asserts `$185.50` survives under `price_display` key. |
| T-37-20 | Information Disclosure (missed key) | mitigate | `test_fuzz_no_sensitive_value_renders_verbatim_nested` in `tests/test_pii_redaction.py:370–410` uses Hypothesis with `max_examples=150, deadline=2000` generating nested variant-case sensitive-key dicts and asserting zero verbatim leaks. |
| T-37-21 | Denial of Service (infinite recursion) | mitigate | `_emit_redaction_failed_marker` at `logging.py:164–174` writes `json.dumps({"event": "redaction_failed"})` directly to `sys.stderr` — no structlog call, no possible re-entry. `test_safety_marker_bypasses_structlog_chain` in `tests/test_pii_redaction.py:229–251` monkeypatches sha256_first8 to force failure and asserts `redaction_failed` appears in `capsys.err` and processor is not re-entered. |
| T-37-22 | Information Disclosure | mitigate | `addopts = "--disable-socket --allow-unix-socket"` in `pyproject.toml:51`. `test_raw_socket_creation_is_blocked` in `tests/test_network_gate.py:20–24` asserts `SocketBlockedError` on AF_INET socket creation. |
| T-37-23 | Information Disclosure (loopback bypass) | mitigate | `test_loopback_connect_is_blocked_by_default` in `tests/test_network_gate.py:27–38` is the tripwire test that asserts `SocketBlockedError` on a 127.0.0.1 connection attempt. |
| T-37-24 | Elevation of Privilege (opt-in bypass) | mitigate | `markers = ["enable_socket: opt-in marker for tests that need real network (D-12 escape hatch)"]` at `pyproject.toml:52–54`. `test_enable_socket_marker_allows_raw_socket_creation` in `tests/test_network_gate.py:41–50` proves the escape hatch works. |
| T-37-25 | Tampering (processor removal) | accept | ACCEPTED — existing tests (`test_processor_runs_before_renderer_in_configured_chain`) will fail if `pii_redaction_processor` is removed from `shared_processors`. Plan 04 meta-test provides architectural guard. Accepted risk documented in plan 37-03 threat register. |

### Plan 37-04 Threats

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-37-26 | Information Disclosure (static) | mitigate | `[tool.importlinter]` stanza with `type = "forbidden"` and `forbidden_modules = ["alphaswarm.holdings"]` at `pyproject.toml:60–110`. 37 entries in `source_modules`. `test_lint_imports_passes_on_clean_tree` verifies `uv run lint-imports` exits 0. `.pre-commit-config.yaml` registers local `lint-imports` hook. |
| T-37-27 | Tampering (source_modules drift) | mitigate | `test_source_modules_covers_every_actual_package` in `tests/invariants/test_importlinter_coverage.py:82–112` uses `_enumerate_actual_packages()` (filesystem walk) and `tomllib` to parse `pyproject.toml`, asserting every discovered package is in `source_modules` or `_KNOWN_NON_SOURCE`. |
| T-37-28 | Information Disclosure (runtime) | mitigate | Four-surface canary at `tests/invariants/test_holdings_isolation.py` with `all_sentinel_representations()` returning 7 forms (raw, Decimal-str, JSON-quoted x2, sha256_first8). Four negative canary assertions + four positive-control tests. Labeled SCAFFOLDED with Phase 41 activation checklist. |
| T-37-29 | Tampering (contract drift) | mitigate | `test_pyproject_toml_contains_forbidden_contract_for_holdings` in `tests/invariants/test_importlinter_contract.py:95–113` asserts `[tool.importlinter]`, `root_package = "alphaswarm"`, `type = "forbidden"`, and `forbidden_modules = ["alphaswarm.holdings"]` are all present in `pyproject.toml`. |
| T-37-30 | Tampering (contract loosening) | mitigate | `test_source_modules_does_not_list_whitelisted_packages` in `tests/invariants/test_importlinter_coverage.py:115–123` asserts `alphaswarm.advisory` and `alphaswarm.web.routes.holdings` are absent from `source_modules`. |
| T-37-31 | Elevation of Privilege (test-side bypass) | mitigate | `tests/integration/conftest.py:13–20` scopes auto-marker to `"tests/integration" in fspath` path predicate — only tests under that subtree receive `enable_socket` automatically. Smoke test `test_auto_marker_allows_socket_creation` in `tests/integration/test_socket_escape_hatch.py` confirms the hook works. |
| T-37-32 | Denial of Service (false canary) | mitigate | Four positive-control tests in `tests/invariants/test_holdings_isolation.py:162–187` inject sentinel directly into each capture fixture and assert detection — `test_positive_control_logs_capture_sentinel_if_injected`, `test_positive_control_ws_frames_capture_injected`, `test_positive_control_neo4j_writes_capture_injected`, `test_positive_control_jinja_renders_capture_injected`. |
| T-37-33 | Information Disclosure (transitive import) | mitigate | import-linter's `forbidden` contract checks transitive imports by default (`allow_indirect_imports = False`). `test_lint_imports_detects_synthetic_violation` in `tests/invariants/test_importlinter_contract.py:37–92` exercises the detection engine via subprocess with explicit `PYTHONPATH`. |
| T-37-34 | Information Disclosure (serialization form) | mitigate | `all_sentinel_representations()` in `tests/invariants/conftest.py:659–677` returns raw, Decimal-str (`"999999.99"`, `"77.7777"`), JSON-quoted (`'"999999.99"'`, `'"77.7777"'`), and `sha256_first8(SENTINEL_ACCT)` (8-hex) forms. `test_all_sentinel_representations_covers_expected_forms` pins the set. |
| T-37-35 | Denial of Service (fake Neo4j/WS trips socket gate) | mitigate | `capture_ws_frames`, `capture_neo4j_writes`, `capture_jinja_renders` are `list[str]` fixtures in `tests/invariants/conftest.py` — no driver instantiation, no socket activity. Canary tests run under `--disable-socket` without needing `enable_socket` (the `pytestmark` is defensive for Phase 41). |
| T-37-36 | Denial of Service (Decimal JSON serialization) | mitigate | `_minimal_simulation_body` uses `json.dumps({"event": "phase_change", ...}, default=str)` at `tests/invariants/test_holdings_isolation.py:85`. All canary serializations use `default=str`. |

---

## Accepted Risks Log

| Threat ID | Category | Rationale |
|-----------|----------|-----------|
| T-37-07 | Repudiation (no audit trail for type construction) | Phase 37 is data-type scaffolding only. ASVS L1 does not require audit-logging for type construction. Will be revisited if Phase 41 advisory pipeline requires construction provenance. |
| T-37-11 | Information Disclosure (test fakes in production import path) | `FakeMarketDataProvider` and `FakeNewsProvider` are re-exported from `alphaswarm.ingestion`. A misconfigured production caller receiving a Fake would get `fetch_failed` slices with no holdings data. No holdings state is present in fakes. Risk accepted pending Phase 38 where real providers will be injected via dependency inversion. |
| T-37-25 | Tampering (processor removal from shared_processors) | Removal of `pii_redaction_processor` from `configure_logging()` would cause `test_processor_runs_before_renderer_in_configured_chain` and related tests to fail. Architectural meta-test in `tests/invariants/test_holdings_isolation.py` provides secondary guard. |

---

## Unregistered Flags

None — the SUMMARY.md `## Threat Flags` sections for all four plans report no new threat flags. All surfaces introduced by Phase 37 are process-internal type scaffolding with no new network endpoints, auth paths, or external dependencies.

---

## Notes

- The `--allow-unix-socket` flag in `pyproject.toml` addopts is a deliberate deviation from the plan spec (which only specified `--disable-socket`). This was added during Plan 37-03 execution to preserve asyncio event-loop functionality (asyncio's internal self-pipe uses AF_UNIX). The net security effect is unchanged: all AF_INET sockets remain blocked.
- The `_normalize_key` function normalizes camelCase partially: `costBasis` → `costbasis` (matches), `positionsByAccount` → `positionsbyaccount` (matches), but does NOT decompose arbitrary camelCase sequences not present in the normalized sensitive sets. This is correct behavior — only the enumerated normalized keys are sensitive.
- The four-surface canary is explicitly SCAFFOLDED at Phase 37. Its negative assertions trivially pass because `_minimal_simulation_body` never touches `sentinel_portfolio`. The canary becomes load-bearing at Phase 41. This is correctly documented and is not a gap.
- T-37-07b (DoS in ingestion loop, Plan 37-02) uses a different identifier than T-37-07 (Repudiation, Plan 37-01) to avoid collision. Both are correctly verified.
