---
phase: 39
plan: 01
subsystem: holdings
tags: [holdings, csv, loader, security, pii, decimal, tdd]
dependency_graph:
  requires:
    - src/alphaswarm/holdings/types.py  # frozen Holding + PortfolioSnapshot (Phase 37)
    - src/alphaswarm/security/hashing.py  # sha256_first8 (Phase 37)
  provides:
    - src/alphaswarm/holdings/loader.py  # HoldingsLoader + HoldingsLoadError
    - src/alphaswarm/holdings/__init__.py  # re-exports all 4 public names
  affects:
    - Plan 39-02  # lifespan wiring: HoldingsLoader.load + HoldingsLoadError catch target
tech_stack:
  added:
    - csv.DictReader (stdlib)
    - decimal.Decimal / InvalidOperation (stdlib)
    - pathlib.Path.stat().st_mtime (stdlib)
    - encoding="utf-8-sig" BOM-transparent CSV open (stdlib)
  patterns:
    - Stateless classmethod loader (Research Recommendation 3)
    - Domain exception pattern (HoldingsLoadError wraps all parse failures)
    - Decimal-from-string construction (never Decimal(float))
    - sha256_first8 of sorted label set for PII-safe account identifier
    - mtime-derived UTC datetime with OSError fallback
key_files:
  created:
    - src/alphaswarm/holdings/loader.py
    - tests/test_holdings_loader.py
  modified:
    - src/alphaswarm/holdings/__init__.py
decisions:
  - HoldingsLoader as class with classmethod load() — easier to mock in Plan 02 lifespan tests
  - Same-ticker multi-account contract locked as separate Holding entries per row (no summing) — preserves IRA vs taxable audit granularity for Phase 41 advisory synthesis
  - as_of from Path.stat().st_mtime with OSError fallback to datetime.now(UTC) — NFS/race safety
  - account_number_hash = sha256_first8("|".join(sorted(account_labels))) — sort-stable, empty-guard before call
  - encoding="utf-8-sig" for BOM-transparent CSV open — handles Schwab web exports silently
metrics:
  duration_minutes: 25
  completed_date: "2026-04-19"
  tasks_completed: 3
  files_changed: 3
requirements_closed: [HOLD-01, HOLD-02]
---

# Phase 39 Plan 01: Holdings Loader — SUMMARY

**One-liner:** HoldingsLoader classmethod reads 4-column Schwab CSV into PortfolioSnapshot with sha256_first8 account hash, Decimal-exact arithmetic, and BOM-transparent UTF-8 opening.

## What Was Built

Two source files and one test file implementing the HOLD-01 + HOLD-02 requirements:

- **`src/alphaswarm/holdings/loader.py`** — `HoldingsLoader` (stateless class with `load(path) -> PortfolioSnapshot` classmethod) and `HoldingsLoadError` domain exception. Opens CSV with `encoding="utf-8-sig"`, parses with `csv.DictReader`, constructs `Decimal(string)` quantities (never float), builds account hash via `sha256_first8("|".join(sorted(account_labels)))`, derives `as_of` from `Path.stat().st_mtime` with OSError fallback, and emits one merged `PortfolioSnapshot` with all rows as a tuple.

- **`src/alphaswarm/holdings/__init__.py`** — Updated to re-export all four public names alphabetically: `["Holding", "HoldingsLoadError", "HoldingsLoader", "PortfolioSnapshot"]`. Import order follows ruff isort (`loader` before `types`).

- **`tests/test_holdings_loader.py`** — 22 hermetic unit tests using `tmp_path` fixtures. No dependency on `Schwab/holdings.csv`. Covers all happy paths, all error paths, the two review-mandated edge cases, and source-level grep invariants.

## Decisions Implemented

| Decision | Rationale |
|----------|-----------|
| D-01: 4-column CSV format (account, symbol, shares, cost_basis_per_share) | Verified against real Schwab export |
| D-02: cost_basis = total (qty × per_share) | Loader multiplies at parse time; `Holding.cost_basis` stores total position cost |
| D-03: Multi-account rows merge into single PortfolioSnapshot | `individual` + `roth_ira` rows appended to same list, one snapshot returned |
| D-04: All positions included (SWYXX money-market passes through) | No filtering by symbol prefix or instrument type |
| HOLD-01: load() returns PortfolioSnapshot with Holding tuples | Core loader contract — unblocks Plan 02 lifespan wiring |
| HOLD-02: Raw account labels hashed before storage | `account_number_hash = sha256_first8("|".join(sorted(account_labels)))` — labels never stored raw on the type |

## Cross-AI Review LOW Concerns Closed

1. **BOM safety (Codex LOW):** `path.open(newline="", encoding="utf-8-sig")` transparently strips UTF-8 BOM prefix if present. Without this, Schwab web exports could corrupt the first header (`\ufeffaccount`) and fail `REQUIRED_COLUMNS`. Verified by `test_load_bom_prefixed_csv` (writes raw `b"\xef\xbb\xbf"` bytes) and `test_loader_module_uses_utf8_sig_encoding` (grep guard on source).

2. **Same-ticker multi-account contract (Gemini + Codex LOW):** D-03 "collapse into one snapshot" was ambiguous about same-ticker rows in different accounts. Contract locked as **separate Holding entries per CSV row, no summing**. Rationale: IRA vs taxable are tax-treatment-distinct lots; per-row granularity preserves audit traceability for Phase 41 advisory synthesis. Verified by `test_same_ticker_multiple_accounts`.

## Pitfalls Mitigated

| Pitfall | Mitigation | Verification |
|---------|-----------|-------------|
| Pitfall 1: Decimal(float) loses precision | Always `Decimal(row["shares"])` and `Decimal(row["cost_basis_per_share"])` | `test_fractional_shares_preserve_decimal_precision` + grep invariant |
| Pitfall 2: sha256_first8("") raises TypeError | `if not rows: raise HoldingsLoadError("CSV has no data rows")` runs BEFORE hash call | `test_load_empty_body_header_only` catches HoldingsLoadError, not TypeError |
| Pitfall 4: importlinter submodule coverage | `alphaswarm.holdings.loader` NOT added to pyproject.toml — exemption at line 101 of invariant test handles `alphaswarm.holdings.*` | `test_importlinter_coverage.py` stays green |
| Pitfall 6: naive datetime | `datetime.fromtimestamp(mtime, tz=UTC)` + `datetime.now(UTC)` fallback | `test_as_of_is_tz_aware_utc` |
| Pitfall 7: logging Holding field values | `log.info("holdings_loaded")` emits only `path`, `count`, `accounts` — never ticker/qty/cost_basis | `test_loader_module_does_not_log_holding_field_values` grep guard |

## Deviations from Plan

None — plan executed exactly as written.

The only minor deviation was a docstring line-length issue caught by ruff (E501 at column 101) which was fixed before commit. The plan's exact file content included a line that slightly exceeded the 100-char ruff limit; wrapped to two lines. No behavioral change.

## Known Stubs

None — `HoldingsLoader.load()` is fully implemented and verified against the real `Schwab/holdings.csv` (34 holdings, correct hash).

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The loader is a read-only stdlib file consumer; all threat mitigations (T-39-01 through T-39-07, T-39-17) from the plan's threat model are implemented.

## Self-Check

- [x] `src/alphaswarm/holdings/loader.py` — created
- [x] `src/alphaswarm/holdings/__init__.py` — updated
- [x] `tests/test_holdings_loader.py` — created
- [x] Commit 621e3b2 — Task 1 skeleton
- [x] Commit 1b55f89 — Task 2 implementation
- [x] Commit f35fbbc — Task 3 tests
- [x] 22 tests pass, 0 failures
- [x] mypy clean (src/alphaswarm/holdings/loader.py)
- [x] ruff clean (loader.py + test_holdings_loader.py)
- [x] lint-imports: 1 kept, 0 broken
- [x] importlinter coverage invariant: 3 passed
- [x] Real CSV verified: 34 holdings, hash = e3ace359

## Self-Check: PASSED
