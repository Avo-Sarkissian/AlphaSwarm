# Phase 21: Restore Ticker Validation and Tracking - Research

**Researched:** 2026-04-08
**Domain:** Python module restoration, SEC ticker validation, Pydantic dataclass fields, CLI output
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TICK-02 | SEC ticker validation — extracted tickers validated against company_tickers.json; invalid symbols rejected with warning | ticker_validator.py code recovered from git history; SEC file present at data/sec_tickers.json |
| TICK-03 | Dropped-ticker tracking — ParsedSeedResult.dropped_tickers restored; CLI injection summary shows dropped symbols when top-3 cap removes them | ParsedSeedResult diff recovered; _print_injection_summary diff recovered; test coverage recovered |

</phase_requirements>

---

## Project Constraints (from CLAUDE.md)

- **Runtime:** Python 3.11+, strict typing, `uv` package manager, `pytest-asyncio`
- **Inference:** Local only via Ollama — no cloud APIs
- **Async:** 100% async for all I/O; `asyncio` throughout
- **Testing:** `pytest-asyncio` with `asyncio_mode = "auto"`
- **Logging:** `structlog` with structured key-value events
- **Validation/Config:** `pydantic` models; frozen where appropriate
- **GSD Workflow:** All file changes must go through a GSD command context

---

## Summary

Phase 21 is a surgical restoration of three capabilities that were deleted wholesale by commit `7ba7efa` ("feat(17-01): install yfinance and define MarketDataSnapshot model"). That commit had a correct stated goal (add yfinance dependency) but destroyed unrelated Phase 16 work as a side effect — deleting `ticker_validator.py`, stripping `parse_seed_event()` of its `ticker_validator` callback parameter, removing `ParsedSeedResult.dropped_tickers`, deleting `tests/test_ticker_validator.py`, and blanking out CLI ticker display code.

The deleted code was already written and tested in Phase 16 (commits `53bf186` and `413d382`). Git history preserves the complete source for all three restoration targets. This phase does not require design decisions or new architecture — it requires exact restoration of code that was previously correct and verified.

The third success criterion — `yfinance>=1.2.0` in `pyproject.toml` — is already satisfied. The dependency was added by commit `7ba7efa` itself and remains in the current `pyproject.toml`. This makes criterion 3 a no-op verification task, not an implementation task.

**Primary recommendation:** Restore the three deleted artifacts directly from git history with minimal modification, then wire them back into the existing call chain exactly as Phase 16 did.

---

## What Was Deleted and What Needs Restoration

### Deletion 1: `src/alphaswarm/ticker_validator.py` (entire file, 123 lines)

Recovered from `git show 7ba7efa -- src/alphaswarm/ticker_validator.py`. The complete file content is known.

**Key behaviors:**
- Module-level `_ticker_set: set[str] | None = None` — process-lifetime lazy cache
- `_load_ticker_set_from_file(path)` — parses SEC JSON dict-of-dicts, uppercases all tickers, returns `set[str]`
- `_download_sec_tickers(dest)` — async httpx GET with `User-Agent: AlphaSwarm admin@alphaswarm.local`, atomic write via temp-file-rename pattern, re-raises `ConnectError` and `TimeoutException` after cleanup
- `ensure_sec_data(data_dir)` — checks if file exists on disk, downloads if missing, returns `Path`
- `get_ticker_validator(data_dir)` — lazy-loads `_ticker_set`, returns `Callable[[str], bool] | None` (None when SEC CDN unreachable and no local file)
- The returned `validate(symbol)` closure does `symbol.upper() in _ticker_set`

**SEC data file status:** `data/sec_tickers.json` already exists on disk (10,433 entries, ~797KB, added by Phase 16 worktree). `ensure_sec_data()` will skip the download path on first call. This is the correct behavior.

**httpx dependency:** `httpx` is NOT declared in `pyproject.toml` `[project.dependencies]` but IS available as a transitive dependency (version 0.28.1 via the lockfile, pulled in by `ollama` or another dep). The original ticker_validator.py imported httpx directly. This is a fragile situation — httpx could disappear if its parent dep drops it — but the REQUIREMENTS.md does not list an httpx direct-dep requirement for this phase. The plan can note this but should not add httpx to pyproject.toml unless explicitly required by the success criteria. The success criteria only require `yfinance>=1.2.0` in dependencies.

### Deletion 2: `ParsedSeedResult.dropped_tickers` field and `parse_seed_event()` callback

**Current state of `types.py`:** `ParsedSeedResult` is a frozen dataclass with only `seed_event: SeedEvent` and `parse_tier: int`. The `dropped_tickers: tuple[dict[str, str], ...]` field is missing.

**Current state of `parsing.py`:**
- `_try_parse_seed_json(text, original_rumor)` — signature has no `ticker_validator` parameter; it parses tickers from JSON but does NOT validate them and does NOT track dropped tickers
- `parse_seed_event(raw, original_rumor)` — signature has no `ticker_validator` parameter; returns `ParsedSeedResult(seed_event=result, parse_tier=N)` with no `dropped_tickers`

**Restoration target (from diff of 7ba7efa):**

1. Add `dropped_tickers: tuple[dict[str, str], ...] = ()` to `ParsedSeedResult` dataclass (after `parse_tier`)
2. Restore `_try_parse_seed_json` signature to `(text, original_rumor, ticker_validator=None)` returning `tuple[SeedEvent | None, list[dict[str, str]]]`
3. Inside `_try_parse_seed_json`, restore the per-ticker SEC validation loop (TICK-02) and the top-3 cap with dropped tracking (TICK-03)
4. Restore `parse_seed_event` signature to accept `ticker_validator: Callable[[str], bool] | None = None`
5. Restore `dropped_tickers=tuple(dropped)` in all `ParsedSeedResult(...)` construction calls (4 call sites within `parse_seed_event`)
6. Restore `from typing import Callable` import in `parsing.py`
7. Restore `ExtractedTicker` import in `parsing.py` (note: `ExtractedTicker` is ALREADY in the current `parsing.py` imports — it was re-added later by Phase 18; no duplicate needed)

**Important note on ExtractedTicker import:** The current `parsing.py` already imports `ExtractedTicker` from `alphaswarm.types` (line 24). The `7ba7efa` diff removed it, but Phase 18 re-added it. The restoration only needs to restore `Callable` from `typing`.

**Backward compatibility:** `ParsedSeedResult.dropped_tickers` defaults to `()`. All existing call sites that construct `ParsedSeedResult` without `dropped_tickers` (Tier 3 fallback in `parse_seed_event`) will continue to work because the field has a default value.

### Deletion 3: Validator wiring in `seed.py`

**Current state:** `inject_seed()` calls `parse_seed_event(raw_content, rumor)` with no validator. No import of `get_ticker_validator`.

**Restoration target (from commit `53bf186`):**
1. Add `from alphaswarm.ticker_validator import get_ticker_validator` import at top of `seed.py`
2. Before the `parse_seed_event` call, add `validator = await get_ticker_validator()`
3. Pass `ticker_validator=validator` to `parse_seed_event`
4. Extend `seed_injection_complete` log with `ticker_count=len(parsed_result.seed_event.tickers)` and `dropped_ticker_count=len(parsed_result.dropped_tickers)`

### Deletion 4: CLI ticker display in `cli.py`

**Current state of `_print_injection_summary()`:** Prints entity count, entity table, and closing separator. No ticker count line, no ticker table, no dropped-ticker section.

**Restoration target (from commit `413d382`):**
1. After `print(f" Entities: {len(seed_event.entities)}")`, add `print(f" Tickers: {len(seed_event.tickers)}")`
2. After the entity table block, add ticker table (Symbol/Company/Relevance headers and rows)
3. After the ticker table, add dropped-ticker section conditioned on `parsed_result.dropped_tickers`

**Exact format recovered:**
```
  Tickers:           {len(seed_event.tickers)}

  Symbol     Company                        Relevance
  ---------- ------------------------------ ----------
  AAPL       Apple Inc                           0.90

  Dropped Tickers:
  ----------------------------------------
  XYZFAKE    (reason: invalid)
  FIFTH      (reason: cap)
```

### Deletion 5: `tests/test_ticker_validator.py` (entire file, 325 lines)

Recovered from `git show 7ba7efa -- tests/test_ticker_validator.py`. All test code is available in git history.

**Test categories in the deleted file:**
- `_load_ticker_set_from_file`: 2 tests (correct symbols, uppercase conversion)
- `validate closure`: 3 async tests (True for valid, case-insensitive, False for unknown)
- `ensure_sec_data`: 2 async tests (no download if file exists, downloads if missing)
- `_download_sec_tickers`: 3 async tests (User-Agent header, atomic tmp+rename, CDN-error cleanup + re-raise)
- `get_ticker_validator`: 5 async tests (ConnectError → None, TimeoutException → None, logs warning with "manually download", ConnectError re-raise, TimeoutException re-raise)
- `autouse` fixture `reset_ticker_cache` resets `tv._ticker_set = None` before and after each test (critical: avoids cross-test cache pollution)

---

## Standard Stack

No new dependencies required. The restoration uses only libraries already in the project.

| Component | Already Available | How |
|-----------|-------------------|-----|
| `httpx` | Yes (0.28.1 transitive) | Used in ticker_validator.py for SEC CDN download |
| `asyncio` | Yes (stdlib) | Async download pattern |
| `structlog` | Yes (declared dep) | Logging in ticker_validator.py |
| `pydantic` | Yes (declared dep) | No changes to pydantic models beyond adding a field |
| `pytest-asyncio` | Yes (dev dep, asyncio_mode=auto) | All async tests work automatically |

**yfinance status:** Already declared as `yfinance>=1.2.0` in `pyproject.toml` line 17 and installed at version 1.2.0. Success criterion 3 is already met — the plan only needs a verification step, not an installation step.

---

## Architecture Patterns

### Pattern: Lazy Module-Level Cache with `autouse` Reset in Tests

The `_ticker_set` module-level variable is set once per process and never reset. Tests must use an `autouse` fixture to reset it between runs to prevent cross-test contamination. This pattern is mandatory.

```python
# In test file (autouse=True ensures every test gets a clean cache)
@pytest.fixture(autouse=True)
def reset_ticker_cache():
    tv._ticker_set = None
    yield
    tv._ticker_set = None
```

### Pattern: Optional Callable Validator (None = Skip Validation)

The validator is optional by design to handle SEC CDN being unreachable on first run. When `get_ticker_validator()` returns `None`, `parse_seed_event()` receives `ticker_validator=None` and skips validation — all extracted tickers are kept. This graceful-degradation pattern must be preserved.

```python
# In seed.py
validator = await get_ticker_validator()  # Returns None if SEC CDN unreachable
parsed_result = parse_seed_event(raw_content, rumor, ticker_validator=validator)
```

### Pattern: Dropped Tickers as Immutable Tuple

`ParsedSeedResult.dropped_tickers` is `tuple[dict[str, str], ...]` (default `()`). Using a tuple (not a list) is consistent with the frozen dataclass pattern used throughout the project. Each dropped entry is `{"symbol": "XYZFAKE", "reason": "invalid"}` or `{"symbol": "FIFTH", "reason": "cap"}`.

### Pattern: Two Reasons for Dropping

```
reason = "invalid"  # ticker_validator returned False for this symbol (TICK-02)
reason = "cap"      # ticker was valid but cut by the top-3 cap (TICK-03)
```

The top-3 cap logic sorts all_tickers by relevance descending, then for `all_tickers[3:]` appends `{"symbol": t.symbol, "reason": "cap"}` to dropped, then trims to `all_tickers[:3]`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SEC symbol lookup | Dict/list search | `set` membership (`symbol.upper() in _ticker_set`) | O(1) vs O(n), 10K+ symbols |
| Atomic file write | Direct write | temp-file + rename pattern (already in codebase) | Prevents partial files on interrupt |
| Async HTTP | Custom socket code | `httpx.AsyncClient` | Already transitive dep, handles timeouts/errors |
| Cache invalidation | TTL logic | None needed — SEC data is stable enough for process lifetime | SEC ticker list rarely changes |

---

## Common Pitfalls

### Pitfall 1: Forgetting `Callable` import in `parsing.py`

**What goes wrong:** `from typing import Callable` was removed in commit `7ba7efa` and must be restored. Without it, the `ticker_validator: Callable[[str], bool] | None = None` type annotation in `_try_parse_seed_json` and `parse_seed_event` will raise a `NameError`.

**How to avoid:** Add `from typing import Callable` back to the imports block in `parsing.py`.

### Pitfall 2: Cross-test cache pollution in `test_ticker_validator.py`

**What goes wrong:** `ticker_validator.py` uses a module-level `_ticker_set` variable. Without the `autouse` fixture that resets `tv._ticker_set = None`, test ordering determines which tests pass.

**How to avoid:** The `reset_ticker_cache` autouse fixture must be the first fixture defined in `test_ticker_validator.py`.

### Pitfall 3: Duplicate `ExtractedTicker` import

**What goes wrong:** The current `parsing.py` already imports `ExtractedTicker` (added back by Phase 18). If the restoration blindly re-adds it, Python will raise a duplicate import error.

**How to avoid:** Only add `Callable` back to the typing import; do NOT add `ExtractedTicker` again.

### Pitfall 4: `ParsedSeedResult` field ordering in frozen dataclass

**What goes wrong:** Python frozen dataclasses with default values cannot precede fields without defaults. `dropped_tickers` has a default of `()` so it must come AFTER `parse_tier: int` (which has no default).

**How to avoid:** Field order: `seed_event: SeedEvent`, `parse_tier: int`, `dropped_tickers: tuple[dict[str, str], ...] = ()`.

### Pitfall 5: SEC file path mismatch

**What goes wrong:** The ticker_validator uses `DEFAULT_FILENAME = "sec_tickers.json"` but the project uses a different filename. The file at `data/sec_tickers.json` matches exactly (`DEFAULT_FILENAME`). But `DEFAULT_DATA_DIR = Path("data")` is a relative path — it resolves relative to the working directory at runtime. When tests run from the project root (which they do with `uv run pytest`), this resolves correctly. No issue for normal use, but tests that need a custom `data_dir` should use `tmp_path` to avoid loading the real 10K-entry SEC file.

### Pitfall 6: `typing.Callable` vs `collections.abc.Callable`

**What goes wrong:** Python 3.11+ prefers `collections.abc.Callable` for runtime use, but the existing codebase uses `from typing import Callable`. Matching the existing style (not introducing a new import style) is the right move for consistency.

**How to avoid:** Use `from typing import Callable` to match the original deleted code and the project's existing patterns.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24+ |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TICK-02 | `_load_ticker_set_from_file` returns correct uppercase symbol set | unit | `uv run pytest tests/test_ticker_validator.py::test_load_ticker_set_returns_expected_symbols -x` | ❌ Wave 0 (restore from git) |
| TICK-02 | `validate()` returns True for known symbol, False for unknown | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_returns_true_for_valid_symbol -x` | ❌ Wave 0 (restore from git) |
| TICK-02 | `validate()` is case-insensitive (lowercase input matches uppercase set) | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_case_insensitive -x` | ❌ Wave 0 (restore from git) |
| TICK-02 | SEC CDN unreachable → `get_ticker_validator()` returns `None` | unit | `uv run pytest tests/test_ticker_validator.py::test_get_ticker_validator_returns_none_on_connect_error -x` | ❌ Wave 0 (restore from git) |
| TICK-02 | `parse_seed_event()` with invalid symbol → symbol in `dropped_tickers` with reason="invalid" | unit | `uv run pytest tests/test_parsing.py -k "drop" -x` | ❌ Wave 0 (new tests) |
| TICK-03 | Top-3 cap: 5 tickers → 3 kept + 2 dropped with reason="cap" | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_tickers_capped_at_3 -x` | ✅ (existing, already passes) |
| TICK-03 | `ParsedSeedResult.dropped_tickers` populated correctly | unit | `uv run pytest tests/test_parsing.py -k "dropped" -x` | ❌ Wave 0 (new tests) |
| TICK-03 | CLI `_print_injection_summary` displays dropped tickers section | unit | `uv run pytest tests/test_cli.py -k "dropped" -x` | ❌ Wave 0 (new tests) |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green (current baseline: 616 passed, 4 warnings, 15 errors in integration tests that require Neo4j)

### Wave 0 Gaps

- [ ] `tests/test_ticker_validator.py` — 325-line file deleted by `7ba7efa`; restore from git verbatim — covers TICK-02
- [ ] New tests in `tests/test_parsing.py` for `dropped_tickers` populated correctly (invalid symbol and cap reason)
- [ ] New tests in `tests/test_cli.py` for dropped ticker CLI display

*(Existing test infrastructure covers pytest setup and all other requirements)*

---

## Code Examples

### Exact `ParsedSeedResult` dataclass (restored)

```python
# Source: git show 7ba7efa -- src/alphaswarm/types.py (before deletion)
@dataclasses.dataclass(frozen=True)
class ParsedSeedResult:
    seed_event: SeedEvent
    parse_tier: int
    dropped_tickers: tuple[dict[str, str], ...] = ()
```

### Exact `_try_parse_seed_json` ticker section (restored)

```python
# Source: git diff 7ba7efa -- src/alphaswarm/parsing.py (removed lines)
# Parse tickers (Phase 16: TICK-01)
dropped: list[dict[str, str]] = []
raw_tickers = data.get("tickers", [])
all_tickers: list[ExtractedTicker] = []
if isinstance(raw_tickers, list):
    for t in raw_tickers:
        try:
            ticker = ExtractedTicker.model_validate(t)
            # SEC validation via callback (TICK-02)
            if ticker_validator and not ticker_validator(ticker.symbol):
                dropped.append({"symbol": ticker.symbol, "reason": "invalid"})
                logger.warning("ticker_invalid", symbol=ticker.symbol)
                continue
            all_tickers.append(ticker)
        except (ValidationError, TypeError):
            continue

# Sort by relevance descending, cap at 3 (TICK-03, per D-05)
all_tickers.sort(key=lambda t: t.relevance, reverse=True)
if len(all_tickers) > 3:
    for t in all_tickers[3:]:
        dropped.append({"symbol": t.symbol, "reason": "cap"})
    all_tickers = all_tickers[:3]
```

### Exact CLI dropped-ticker display (restored)

```python
# Source: git show 413d382 -- src/alphaswarm/cli.py
print(f"  Tickers:           {len(seed_event.tickers)}")

# Ticker table (Phase 16: TICK-03 per D-11)
if seed_event.tickers:
    print(f"\n  {'Symbol':<10} {'Company':<30} {'Relevance':>10}")
    print(f"  {'-'*10} {'-'*30} {'-'*10}")
    for ticker in seed_event.tickers:
        print(
            f"  {ticker.symbol:<10} {ticker.company_name:<30} "
            f"{ticker.relevance:>10.2f}"
        )

# Dropped tickers with reason labels (Phase 16: TICK-03 per D-12)
if parsed_result.dropped_tickers:
    print(f"\n  Dropped Tickers:")
    print(f"  {'-'*40}")
    for d in parsed_result.dropped_tickers:
        print(f"  {d['symbol']:<10} (reason: {d['reason']})")
```

### Exact `seed.py` validator wiring (restored)

```python
# Source: git show 53bf186 -- src/alphaswarm/seed.py
from alphaswarm.ticker_validator import get_ticker_validator  # added import

# Inside inject_seed(), before parse_seed_event call:
validator = await get_ticker_validator()
parsed_result = parse_seed_event(raw_content, rumor, ticker_validator=validator)

# Extended log:
logger.info(
    "seed_injection_complete",
    cycle_id=cycle_id,
    entity_count=len(parsed_result.seed_event.entities),
    ticker_count=len(parsed_result.seed_event.tickers),
    dropped_ticker_count=len(parsed_result.dropped_tickers),
    overall_sentiment=parsed_result.seed_event.overall_sentiment,
    parse_tier=parsed_result.parse_tier,
    modifier_parse_tier=modifier_result.parse_tier if modifier_result else None,
)
```

---

## Environment Availability

Step 2.6: No new external tools required. All dependencies already available.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| httpx | ticker_validator.py SEC download | Yes (transitive) | 0.28.1 | None needed |
| yfinance | pyproject.toml criterion 3 | Yes (direct dep) | 1.2.0 | N/A |
| data/sec_tickers.json | SEC validation offline | Yes (on disk) | 10,433 entries | Download via httpx |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

---

## Open Questions

1. **Should httpx be added as a direct dependency?**
   - What we know: httpx is used by ticker_validator.py but not declared in `pyproject.toml`. It's available as a transitive dep (0.28.1).
   - What's unclear: The success criteria do not require this. If `ollama` or another dep eventually drops httpx, ticker_validator.py would silently break.
   - Recommendation: Raise this as a follow-up item. Do not add it in this phase — the success criteria don't cover it and it risks scope creep.

2. **Do any callers of `ParsedSeedResult` besides `seed.py` and `cli.py` need updating?**
   - What we know: `grep` of the codebase shows `ParsedSeedResult` is used in `seed.py` (construction), `cli.py` (`_print_injection_summary`), and test files. The `parse_seed_event()` function signature change is backward-compatible because `ticker_validator` defaults to `None`.
   - What's unclear: Any integration tests that construct `ParsedSeedResult(seed_event=..., parse_tier=N)` without `dropped_tickers` will continue to work because the field has a default.
   - Recommendation: No additional callers need updating.

---

## State of the Art

| Old Approach (Phase 16, before 7ba7efa) | Deleted by 7ba7efa | Restored by Phase 21 |
|------------------------------------------|--------------------|----------------------|
| `ticker_validator.py` with lazy SEC validation | Deleted | Restored |
| `ParsedSeedResult.dropped_tickers` field | Removed | Restored |
| `parse_seed_event(validator=...)` callback | Removed | Restored |
| CLI dropped-ticker display | Removed | Restored |
| `tests/test_ticker_validator.py` (325 lines) | Deleted | Restored |
| `yfinance>=1.2.0` in pyproject.toml | Added by 7ba7efa | Already present — no action |

---

## Sources

### Primary (HIGH confidence)

- `git show 7ba7efa` — exact diff of all deletions; provides complete source for all restoration targets
- `git show 53bf186` — Phase 16-03 seed.py wiring commit
- `git show 413d382` — Phase 16-03 CLI display commit
- `src/alphaswarm/parsing.py` (current) — confirmed current state; shows what is missing
- `src/alphaswarm/types.py` (current) — confirmed `ParsedSeedResult` missing `dropped_tickers`
- `src/alphaswarm/seed.py` (current) — confirmed no `get_ticker_validator` import or call
- `pyproject.toml` (current) — confirmed `yfinance>=1.2.0` already present (criterion 3 done)
- `data/sec_tickers.json` (on disk) — confirmed present, 10,433 entries

### Secondary (MEDIUM confidence)

- `uv run pytest -q` output — baseline: 616 passed, 15 errors (all Neo4j integration tests)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies already present, no new installs
- Architecture: HIGH — entire deleted code recovered verbatim from git history
- Pitfalls: HIGH — identified from careful diff analysis of the deletion commit
- Test gaps: HIGH — full test file content available from git history

**Research date:** 2026-04-08
**Valid until:** This research is based on stable git history — no expiry
