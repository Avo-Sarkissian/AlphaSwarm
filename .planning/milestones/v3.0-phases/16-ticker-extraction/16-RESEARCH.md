# Phase 16: Ticker Extraction - Research

**Researched:** 2026-04-05
**Domain:** LLM-based ticker extraction, SEC symbol validation, Pydantic type extension
**Confidence:** HIGH

## Summary

Phase 16 extends the existing `inject_seed()` pipeline to co-extract stock ticker symbols alongside entities in a single orchestrator LLM call. Extracted tickers are validated against the SEC `company_tickers.json` symbol table (downloaded once from the SEC CDN), capped at 3 by relevance score, and stored as a list property on the Neo4j `Cycle` node. This is a surgical extension of 5 existing files plus one new module (`ticker_validator.py`), with no new inference calls, no new model loads, and no changes to the simulation engine.

The codebase already has all the patterns needed: `SeedEntity` is the template for `ExtractedTicker`, `_try_parse_seed_json()` already does per-item validation with graceful skip, and `_print_injection_summary()` already renders entity tables. The research below provides exact specifications for each change point so the planner can produce tasks that are copy-paste precise.

**Primary recommendation:** Implement as 4 focused tasks: (1) types + ticker validator module, (2) prompt + parsing changes, (3) graph + seed pipeline integration, (4) CLI display + tests.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Ticker extraction is co-located in `seed.py` -- the existing `ORCHESTRATOR_SYSTEM_PROMPT` and `inject_seed()` are augmented to produce tickers alongside entities in a single LLM call. No second LLM call, no second model load.
- **D-02:** The orchestrator's JSON response schema expands from `{"entities": [...], "overall_sentiment": float}` to include a `"tickers": [...]` array. The parse path in `parsing.py::parse_seed_event()` is updated to read this new field.
- **D-03:** A new `ExtractedTicker` Pydantic model is added to `types.py`, parallel to `SeedEntity` (lines 79-85). Fields: `symbol: str`, `company_name: str`, `relevance: float`.
- **D-04:** `SeedEvent` gains a `tickers: list[ExtractedTicker]` field. All downstream consumers receive tickers automatically via the existing `SeedEvent` object.
- **D-05:** The 3-ticker cap (TICK-03) is enforced at parse time in `parse_seed_event()` -- sort by relevance descending, keep top-3 before constructing the `SeedEvent`.
- **D-06:** `company_tickers.json` is loaded from disk as an in-memory dict. The file is fetched once from the SEC CDN and stored in a project data directory. A lazy-load helper loads it on first use and caches it for the process lifetime.
- **D-07:** Validation is a synchronous in-memory dict lookup. Invalid symbols are rejected with a `structlog` warning. Simulation does not abort -- it continues with only validated tickers. If all tickers fail validation, simulation proceeds with `tickers=[]` and a clear warning.
- **D-08:** The SEC file download is a one-time setup step exposed as a CLI utility or auto-triggered on first `inject` run when the file is missing.
- **D-09:** Extracted tickers are stored as a property on the `Cycle` node (`tickers: ["AAPL", "TSLA"]`) -- no separate `Ticker` nodes in Phase 16.
- **D-10:** `graph.py::create_cycle_with_seed_event()` is updated to include the `tickers` list in the Cypher write.
- **D-11:** Ticker selection result displayed by extending `_print_injection_summary()` in `cli.py`.
- **D-12:** Dropped tickers shown with reason label (`"cap"` or `"invalid"`).

### Claude's Discretion
- SEC data directory name and path (e.g., `data/sec_tickers.json` vs `.alphaswarm/sec_tickers.json`)
- Whether SEC auto-download uses `httpx` (already a dependency) or `urllib.request`
- Exact `ORCHESTRATOR_SYSTEM_PROMPT` wording for the `tickers` field instruction
- Whether `ExtractedTicker` is a frozen Pydantic model or a dataclass (follow `SeedEntity` pattern)
- Whether the `setup-data` CLI subcommand is added in Phase 16 or the download is purely auto-triggered

### Deferred Ideas (OUT OF SCOPE)
- `Ticker` nodes in Neo4j with `MENTIONS` edges to Cycle -- deferred to Phase 17
- Fuzzy company-name matching against SEC table -- out of scope
- Ticker persistence to a local watchlist / user preferences -- future milestone
- Multi-session SEC data refresh / staleness checking -- Phase 16 does one-time download
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TICK-01 | Orchestrator extracts stock tickers from seed rumor text alongside existing entity extraction | Prompt engineering section provides exact ORCHESTRATOR_SYSTEM_PROMPT expansion; single LLM call confirmed feasible by existing pattern |
| TICK-02 | Extracted tickers are validated against SEC company_tickers.json symbol table before use | SEC file schema documented, download URL confirmed, lazy-load + in-memory set lookup pattern specified |
| TICK-03 | Simulation caps at 3 tickers per run, ranked by relevance score from extraction | Parse-time enforcement in `_try_parse_seed_json()` with sort-by-relevance + slice[:3]; CLI displays kept/dropped with reason |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). The SEC download must use `httpx.AsyncClient` or `asyncio.to_thread()` wrapping a sync call. The validation lookup itself is synchronous (in-memory dict) and fine to call without async.
- **Local First:** No cloud APIs. SEC CDN is a public data endpoint, not a cloud API -- acceptable per the "except Miro" exception pattern.
- **Memory Safety:** SEC `company_tickers.json` is ~2.5MB raw, ~10K entries. Loading into a `set[str]` of ticker symbols uses negligible memory (~100KB). No memory concern.
- **Runtime:** Python 3.11+ strict typing. All new models must be fully typed.
- **Validation/Config:** Pydantic for all data models. `ExtractedTicker` must be a frozen Pydantic `BaseModel`.
- **Logging/HTTP:** `structlog` for all logging, `httpx` for HTTP calls.
- **Package manager:** `uv`. No new dependencies needed -- `httpx` already in deps.
- **Testing:** `pytest-asyncio`. Tests run via `uv run pytest`.

## Implementation Approach

### TICK-01: Co-Extraction in Single LLM Call

The existing `ORCHESTRATOR_SYSTEM_PROMPT` (seed.py:24-36) instructs the LLM to output `{"entities": [...], "overall_sentiment": float}`. The prompt is expanded to also request a `"tickers"` array. The LLM already uses `format="json"` and `think=True`. No additional inference call needed.

**Key insight:** The LLM is already extracting company entities with names like "NVIDIA", "Tesla", "Apple". Adding a parallel instruction to emit ticker symbols leverages the same reasoning step. The relevance score mirrors the existing `SeedEntity.relevance` pattern.

### TICK-02: SEC Validation

A new module `src/alphaswarm/ticker_validator.py` handles:
1. Downloading `company_tickers.json` from SEC CDN (one-time, auto-triggered)
2. Loading the file into an in-memory `set[str]` of uppercase ticker symbols
3. Validating extracted tickers via `symbol.upper() in ticker_set`

The SEC file is ~2.5MB, containing ~10,000 entries. Download takes <5 seconds on any connection. The file is stored at `data/sec_tickers.json` (project root, gitignored).

### TICK-03: 3-Ticker Cap with Relevance Ranking

Enforced in `parsing.py::_try_parse_seed_json()` after parsing all tickers:
1. Sort by `relevance` descending
2. Keep top 3
3. Return both kept and dropped lists (dropped tagged with reason `"cap"`)

Tickers that fail SEC validation are removed before the cap is applied (tagged with reason `"invalid"`).

## SEC company_tickers.json

### Download URL
```
https://www.sec.gov/files/company_tickers.json
```

**Confidence:** HIGH -- this is the official SEC EDGAR endpoint, stable for years.

### Required Headers
The SEC requires a `User-Agent` header containing an email address on all API requests. Requests without this header receive HTTP 403.

```python
headers = {"User-Agent": "AlphaSwarm admin@alphaswarm.local"}
```

### File Schema
```json
{
  "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
  "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
  "2": {"cik_str": 1318605, "ticker": "TSLA", "title": "TESLA INC"},
  ...
}
```

- **Top-level:** Object with string-numeric keys (`"0"`, `"1"`, ..., `"~10000"`)
- **Each entry:** `{"cik_str": int, "ticker": str, "title": str}`
- **Ticker field:** Uppercase stock symbol (e.g., `"AAPL"`, `"MSFT"`)
- **Title field:** SEC-conformed company name (all caps or mixed case)
- **Total entries:** ~10,000+ (all SEC-filing companies)

### Loading Strategy

```python
import json
from pathlib import Path

def _load_ticker_set(path: Path) -> set[str]:
    """Load SEC tickers into an uppercase symbol set for O(1) lookup."""
    with path.open() as f:
        data = json.load(f)
    return {entry["ticker"].upper() for entry in data.values()}
```

This produces a `set[str]` of ~10K uppercase symbols. Lookup is O(1). Memory cost is negligible (~100KB for 10K short strings).

### Storage Location

**Recommendation:** `data/sec_tickers.json` in the project root.
- Add `data/` to `.gitignore` (the file is 2.5MB and should not be committed)
- Create `data/` directory if it does not exist during download
- The SEC file changes infrequently (~quarterly when new companies file); one-time download is sufficient for Phase 16

## Prompt Engineering

### Current ORCHESTRATOR_SYSTEM_PROMPT (seed.py:24-36)

```python
ORCHESTRATOR_SYSTEM_PROMPT = """You are a financial intelligence analyst. Given a market rumor, extract all named entities and assess sentiment.

For each entity, determine:
- name: The entity name (company, sector, or person)
- type: One of "company", "sector", or "person"
- relevance: How central this entity is to the rumor (0.0-1.0)
- sentiment: The rumor's implication for this entity (-1.0 bearish to 1.0 bullish)

Also determine overall_sentiment for the entire rumor (-1.0 to 1.0).

Be thorough: extract ALL entities mentioned or strongly implied. Include sectors affected even if not named directly. Assign relevance based on centrality to the rumor's core claim.

Respond with JSON: {"entities": [...], "overall_sentiment": float}"""
```

### Expanded ORCHESTRATOR_SYSTEM_PROMPT

```python
ORCHESTRATOR_SYSTEM_PROMPT = """You are a financial intelligence analyst. Given a market rumor, extract all named entities, identify stock tickers, and assess sentiment.

For each entity, determine:
- name: The entity name (company, sector, or person)
- type: One of "company", "sector", or "person"
- relevance: How central this entity is to the rumor (0.0-1.0)
- sentiment: The rumor's implication for this entity (-1.0 bearish to 1.0 bullish)

For each publicly traded company mentioned or implied, determine:
- symbol: The stock ticker symbol (e.g., "AAPL", "TSLA", "MSFT")
- company_name: The full company name
- relevance: How central this company is to the rumor (0.0-1.0)

Also determine overall_sentiment for the entire rumor (-1.0 to 1.0).

Be thorough: extract ALL entities mentioned or strongly implied. Include sectors affected even if not named directly. For tickers, only include companies that are publicly traded on major US exchanges. Assign relevance based on centrality to the rumor's core claim.

Respond with JSON: {"entities": [...], "tickers": [...], "overall_sentiment": float}"""
```

**Key design choices:**
- Tickers are separate from entities (different schema: `symbol` vs `name`, no `type`/`sentiment` on tickers)
- The prompt explicitly says "publicly traded on major US exchanges" to avoid spurious symbols
- The prompt explicitly shows the expected field names (`symbol`, `company_name`, `relevance`) so the LLM outputs the right JSON keys
- The response schema is shown in the final line to anchor the LLM's output structure

## Type Model

### New: ExtractedTicker (types.py)

```python
class ExtractedTicker(BaseModel, frozen=True):
    """A stock ticker extracted from a seed rumor and validated against SEC data."""

    symbol: str
    company_name: str
    relevance: float = Field(ge=0.0, le=1.0)
```

**Follows SeedEntity pattern exactly:** frozen Pydantic BaseModel with `Field` constraints. Placed immediately after `SeedEntity` (after line 85) in `types.py`.

### Modified: SeedEvent (types.py)

```python
class SeedEvent(BaseModel, frozen=True):
    """Structured seed rumor with extracted entities, tickers, and aggregate sentiment."""

    raw_rumor: str
    entities: list[SeedEntity]
    tickers: list[ExtractedTicker] = Field(default_factory=list)
    overall_sentiment: float = Field(ge=-1.0, le=1.0)
```

**Key:** `tickers` has a default of empty list (`default_factory=list`) so existing code that constructs `SeedEvent` without tickers continues to work. This is critical for backward compatibility with:
- `conftest.py:sample_seed_event` fixture (line 106-117)
- Tier 3 fallback in `parse_seed_event()` (line 214-216)
- All existing tests

### No Changes Needed

- `ParsedSeedResult` -- wraps `SeedEvent`, automatically includes tickers
- `ParsedModifiersResult` -- unrelated
- `AgentDecision` -- ticker-specific fields are Phase 18 (DECIDE-01)

## Parsing Changes

### Modified: _try_parse_seed_json() (parsing.py)

The function currently reads `entities` and `overall_sentiment` from parsed JSON. It needs to also read `tickers`, validate each one individually (skip invalid), sort by relevance, and cap at 3.

```python
def _try_parse_seed_json(
    text: str,
    original_rumor: str,
    ticker_validator: Callable[[str], bool] | None = None,
) -> tuple[SeedEvent | None, list[dict[str, str]]]:
    """Attempt to parse text as JSON into SeedEvent.

    Returns (SeedEvent | None, dropped_tickers) where dropped_tickers
    is a list of {"symbol": str, "reason": "invalid"|"cap"} dicts.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, []

    if not isinstance(data, dict):
        return None, []

    try:
        # Parse entities (existing logic, unchanged)
        raw_entities = data.get("entities", [])
        if not isinstance(raw_entities, list):
            return None, []
        entities: list[SeedEntity] = []
        for e in raw_entities:
            try:
                entities.append(SeedEntity.model_validate(e))
            except (ValidationError, TypeError):
                continue

        # Parse tickers (new)
        dropped: list[dict[str, str]] = []
        raw_tickers = data.get("tickers", [])
        all_tickers: list[ExtractedTicker] = []
        if isinstance(raw_tickers, list):
            for t in raw_tickers:
                try:
                    ticker = ExtractedTicker.model_validate(t)
                    # SEC validation
                    if ticker_validator and not ticker_validator(ticker.symbol):
                        dropped.append({"symbol": ticker.symbol, "reason": "invalid"})
                        logger.warning("ticker_invalid", symbol=ticker.symbol)
                        continue
                    all_tickers.append(ticker)
                except (ValidationError, TypeError):
                    continue

        # Sort by relevance descending, cap at 3 (TICK-03)
        all_tickers.sort(key=lambda t: t.relevance, reverse=True)
        if len(all_tickers) > 3:
            for t in all_tickers[3:]:
                dropped.append({"symbol": t.symbol, "reason": "cap"})
            all_tickers = all_tickers[:3]

        overall_sentiment = float(data.get("overall_sentiment", 0.0))
        return SeedEvent(
            raw_rumor=original_rumor,
            entities=entities,
            tickers=all_tickers,
            overall_sentiment=overall_sentiment,
        ), dropped
    except (ValidationError, TypeError, ValueError, KeyError):
        return None, []
```

### Modified: parse_seed_event() (parsing.py)

The public function needs to:
1. Pass a `ticker_validator` callback through to `_try_parse_seed_json()`
2. Collect dropped tickers from the parse result
3. Return them alongside `ParsedSeedResult`

**Design choice:** Rather than changing the `ParsedSeedResult` dataclass (which would break many downstream consumers), add a new dataclass or extend the return to include dropped ticker info. The simplest approach: add a `dropped_tickers` field to `ParsedSeedResult`.

```python
@dataclasses.dataclass(frozen=True)
class ParsedSeedResult:
    """Result of parse_seed_event() with parse-tier observability."""

    seed_event: SeedEvent
    parse_tier: int
    dropped_tickers: tuple[dict[str, str], ...] = ()  # New field with default
```

The `tuple` type with default `()` maintains backward compatibility -- existing code constructing `ParsedSeedResult(seed_event=..., parse_tier=...)` still works.

### ticker_validator Callback Pattern

The `parse_seed_event()` function receives an optional `ticker_validator: Callable[[str], bool] | None` parameter. This keeps parsing.py free of direct dependencies on the SEC data module. The caller (`seed.py:inject_seed()`) provides the callback:

```python
from alphaswarm.ticker_validator import get_ticker_validator

validator = await get_ticker_validator(settings)
parsed_result = parse_seed_event(raw_content, rumor, ticker_validator=validator)
```

## Ticker Validator Module

### New file: src/alphaswarm/ticker_validator.py

```python
"""SEC ticker symbol validation for AlphaSwarm.

Loads company_tickers.json from SEC CDN (one-time download),
caches as in-memory set for O(1) symbol lookup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings

logger = structlog.get_logger(component="ticker_validator")

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "AlphaSwarm admin@alphaswarm.local"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_FILENAME = "sec_tickers.json"

# Module-level cache (lazy-loaded, process-lifetime)
_ticker_set: set[str] | None = None


def _load_ticker_set_from_file(path: Path) -> set[str]:
    """Parse SEC JSON into uppercase ticker symbol set."""
    with path.open() as f:
        data = json.load(f)
    return {entry["ticker"].upper() for entry in data.values()}


async def _download_sec_tickers(dest: Path) -> None:
    """Download company_tickers.json from SEC CDN."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            SEC_TICKERS_URL,
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=30.0,
        )
        response.raise_for_status()
        dest.write_bytes(response.content)
    logger.info("sec_tickers_downloaded", path=str(dest), size_bytes=dest.stat().st_size)


async def ensure_sec_data(data_dir: Path | None = None) -> Path:
    """Ensure SEC tickers file exists on disk. Download if missing."""
    directory = data_dir or DEFAULT_DATA_DIR
    path = directory / DEFAULT_FILENAME
    if not path.exists():
        logger.info("sec_tickers_missing_downloading", path=str(path))
        await _download_sec_tickers(path)
    return path


async def get_ticker_validator(
    data_dir: Path | None = None,
) -> callable:
    """Return a sync validation function: symbol -> bool.

    Downloads SEC data if missing. Caches ticker set in module-level variable.
    """
    global _ticker_set
    if _ticker_set is None:
        path = await ensure_sec_data(data_dir)
        _ticker_set = _load_ticker_set_from_file(path)
        logger.info("sec_tickers_loaded", count=len(_ticker_set))

    def validate(symbol: str) -> bool:
        return symbol.upper() in _ticker_set

    return validate
```

**Key design decisions:**
- Uses `httpx.AsyncClient` (already a dependency, satisfies async constraint)
- Module-level `_ticker_set` cache (matches `config.py` singleton pattern per CONTEXT.md D-06)
- Validator returned as a closure -- keeps `parsing.py` dependency-free
- `User-Agent` header set per SEC requirement (HTTP 403 without it)
- `timeout=30.0` to avoid hanging on slow connections
- `data_dir` parameter allows test injection of temp directories

## Graph Changes

### Modified: create_cycle_with_seed_event() (graph.py)

The `Cycle` node needs a `tickers` property (list of strings). Neo4j natively supports list properties.

#### Parameter extraction (graph.py:192-199)

Add ticker symbols list extraction:

```python
ticker_symbols = [t.symbol for t in seed_event.tickers]
```

#### Transaction method (graph.py:223-258)

The `_create_cycle_with_entities_tx` static method gains a `tickers` parameter:

```python
@staticmethod
async def _create_cycle_with_entities_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    seed_rumor: str,
    overall_sentiment: float,
    entities: list[dict],
    tickers: list[str],  # New parameter
) -> None:
    """Single transaction: create Cycle with tickers, then UNWIND Entity+MENTIONS."""
    await tx.run(
        """
        CREATE (c:Cycle {
            cycle_id: $cycle_id,
            seed_rumor: $seed_rumor,
            overall_sentiment: $overall_sentiment,
            tickers: $tickers,
            created_at: datetime()
        })
        """,
        cycle_id=cycle_id,
        seed_rumor=seed_rumor,
        overall_sentiment=overall_sentiment,
        tickers=tickers,
    )
    # Entity UNWIND unchanged
    if entities:
        await tx.run(
            """
            UNWIND $entities AS e
            MERGE (entity:Entity {name: e.name, type: e.type})
            WITH entity, e
            MATCH (c:Cycle {cycle_id: $cycle_id})
            CREATE (c)-[:MENTIONS {relevance: e.relevance, sentiment: e.sentiment}]->(entity)
            """,
            entities=entities,
            cycle_id=cycle_id,
        )
```

**Key:** `tickers: $tickers` passes a Python `list[str]` which Neo4j stores as a native list property. Empty list `[]` is valid and stores as an empty list property (not null).

## CLI Changes

### Modified: _print_injection_summary() (cli.py:65-90)

Add a tickers section after the entity table. Display both kept tickers and dropped tickers with reasons.

```python
def _print_injection_summary(
    cycle_id: str,
    parsed_result: ParsedSeedResult,
) -> None:
    """Print a formatted summary of the seed injection result."""
    seed_event = parsed_result.seed_event
    tier_labels = {1: "direct JSON", 2: "extracted/cleaned", 3: "FALLBACK (parse failed)"}
    tier_label = tier_labels.get(parsed_result.parse_tier, "unknown")

    print(f"\n{'='*60}")
    print("  Seed Injection Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID:          {cycle_id}")
    print(f"  Overall Sentiment: {seed_event.overall_sentiment:+.2f}")
    print(f"  Parse Quality:     Tier {parsed_result.parse_tier} ({tier_label})")
    print(f"  Entities:          {len(seed_event.entities)}")
    print(f"  Tickers:           {len(seed_event.tickers)}")

    if seed_event.entities:
        print(f"\n  {'Name':<25} {'Type':<10} {'Relevance':>10} {'Sentiment':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for entity in seed_event.entities:
            print(
                f"  {entity.name:<25} {entity.type.value:<10} "
                f"{entity.relevance:>10.2f} {entity.sentiment:>+10.2f}"
            )

    # Ticker section (new)
    if seed_event.tickers:
        print(f"\n  {'Symbol':<10} {'Company':<30} {'Relevance':>10}")
        print(f"  {'-'*10} {'-'*30} {'-'*10}")
        for ticker in seed_event.tickers:
            print(
                f"  {ticker.symbol:<10} {ticker.company_name:<30} "
                f"{ticker.relevance:>10.2f}"
            )

    # Dropped tickers (from ParsedSeedResult.dropped_tickers)
    if parsed_result.dropped_tickers:
        print(f"\n  Dropped Tickers:")
        print(f"  {'-'*40}")
        for d in parsed_result.dropped_tickers:
            print(f"  {d['symbol']:<10} (reason: {d['reason']})")

    print(f"{'='*60}\n")
```

**Visual contract:** The ticker table mirrors the entity table style -- left-aligned labels, right-aligned numbers. Dropped tickers are shown below with reason labels per D-12.

## Architecture Patterns

### Recommended Change Structure

```
src/alphaswarm/
  types.py              # + ExtractedTicker model, SeedEvent.tickers field
  ticker_validator.py   # NEW: SEC download + lazy-load + validate()
  parsing.py            # + tickers parsing in _try_parse_seed_json(), top-3 cap
  seed.py               # + expanded ORCHESTRATOR_SYSTEM_PROMPT, validator wiring
  graph.py              # + tickers property on Cycle node Cypher
  cli.py                # + tickers display in _print_injection_summary()
data/
  sec_tickers.json      # Downloaded at runtime (gitignored)
tests/
  test_ticker_validator.py  # NEW: SEC loading, validation, download mock
  test_seed.py              # + ExtractedTicker model tests
  test_parsing.py           # + tickers parsing tests, cap tests
```

### Anti-Patterns to Avoid
- **Second LLM call for tickers:** D-01 explicitly prohibits this. Tickers are co-extracted in the same prompt.
- **Fuzzy matching against SEC data:** Out of scope per deferred ideas. Symbol must be an exact uppercase match.
- **Ticker nodes in Neo4j:** Deferred to Phase 17. Use a simple list property on Cycle.
- **Bundling SEC data in repo:** The file is ~2.5MB and updates quarterly. Download at runtime.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SEC symbol validation | Custom scraper / manual symbol list | SEC `company_tickers.json` CDN | Official, comprehensive (~10K symbols), free, no API key |
| HTTP download | `urllib.request` | `httpx.AsyncClient` | Already a dependency; async-compatible; proper timeout/error handling |
| JSON parsing | Custom regex ticker extraction | `json.loads()` + Pydantic `model_validate()` | Existing 3-tier pattern handles all edge cases |
| Ticker ranking | Custom scoring algorithm | LLM `relevance` float + sort | LLM already scores relevance for entities; same pattern for tickers |

## Common Pitfalls

### Pitfall 1: SEC CDN Returns 403 Without User-Agent
**What goes wrong:** HTTP 403 Forbidden when fetching `company_tickers.json`.
**Why it happens:** SEC requires a `User-Agent` header with a contact email on all requests.
**How to avoid:** Always set `headers={"User-Agent": "AlphaSwarm admin@alphaswarm.local"}` on the httpx request.
**Warning signs:** `httpx.HTTPStatusError` with status 403 during first run.

### Pitfall 2: LLM Emits Invalid Ticker Symbols
**What goes wrong:** LLM outputs symbols like `"APPLE"` instead of `"AAPL"`, or fabricates non-existent symbols.
**Why it happens:** LLMs are not reliable ticker databases; they hallucinate symbols.
**How to avoid:** SEC validation rejects invalid symbols with a warning (D-07). The prompt explicitly instructs "stock ticker symbol (e.g., AAPL, TSLA, MSFT)" to anchor the format.
**Warning signs:** High rate of `ticker_invalid` log warnings across multiple runs.

### Pitfall 3: Empty Tickers on Old Prompts / Tier 3 Fallback
**What goes wrong:** `SeedEvent.tickers` is always empty because the LLM didn't include tickers in its output.
**Why it happens:** LLM ignores the ticker instruction, or the output gets corrupted, or the parse falls to Tier 3.
**How to avoid:** `tickers: list[ExtractedTicker] = Field(default_factory=list)` ensures empty list is valid. Tier 3 fallback returns `tickers=[]`. Simulation proceeds normally with no tickers -- this is acceptable per D-07.
**Warning signs:** `parse_tier=3` in logs, or `parse_tier=1` with `ticker_count=0`.

### Pitfall 4: SEC File Download Blocks Event Loop
**What goes wrong:** Synchronous file download blocks the asyncio event loop during first run.
**Why it happens:** Using `requests.get()` or `urllib.request.urlopen()` instead of async httpx.
**How to avoid:** Use `httpx.AsyncClient` for the download. The `_download_sec_tickers()` function is async.
**Warning signs:** Event loop warning about slow callback.

### Pitfall 5: Backward Compatibility Break in ParsedSeedResult
**What goes wrong:** Existing tests that construct `ParsedSeedResult(seed_event=..., parse_tier=...)` break.
**Why it happens:** Adding a required `dropped_tickers` field without a default.
**How to avoid:** Use `dropped_tickers: tuple[dict[str, str], ...] = ()` with a default empty tuple. Frozen dataclass with default field works when placed after non-default fields.
**Warning signs:** `TypeError: __init__() missing required argument` in test failures.

### Pitfall 6: Case Sensitivity in Ticker Validation
**What goes wrong:** LLM outputs `"aapl"` lowercase, SEC data has `"AAPL"` uppercase, validation fails.
**Why it happens:** LLMs don't consistently case ticker symbols.
**How to avoid:** Always uppercase the symbol before lookup: `symbol.upper() in _ticker_set`. The `ExtractedTicker` model stores the symbol as-is from the LLM, but validation normalizes.
**Warning signs:** Valid tickers being rejected in logs.

### Pitfall 7: Neo4j List Property With Empty List
**What goes wrong:** Concern that `tickers: []` might cause Neo4j issues.
**Why it happens:** Unfamiliarity with Neo4j list property handling.
**How to avoid:** Neo4j handles empty list properties natively. `CREATE (c:Cycle {tickers: []})` is valid Cypher and stores an empty list. No special handling needed.
**Warning signs:** None -- this is a non-issue, noted to prevent unnecessary defensive code.

## Code Examples

### Example 1: Full LLM Response (Expected)
```json
{
  "entities": [
    {"name": "Apple", "type": "company", "relevance": 0.95, "sentiment": 0.7},
    {"name": "Tesla", "type": "company", "relevance": 0.9, "sentiment": -0.3},
    {"name": "Electric Vehicles", "type": "sector", "relevance": 0.6, "sentiment": 0.4}
  ],
  "tickers": [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.95},
    {"symbol": "TSLA", "company_name": "Tesla Inc.", "relevance": 0.9}
  ],
  "overall_sentiment": 0.3
}
```

### Example 2: LLM Response With >3 Tickers (Cap Applied)
```json
{
  "entities": [...],
  "tickers": [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.95},
    {"symbol": "TSLA", "company_name": "Tesla Inc.", "relevance": 0.9},
    {"symbol": "GOOG", "company_name": "Alphabet Inc.", "relevance": 0.7},
    {"symbol": "NVDA", "company_name": "NVIDIA Corp.", "relevance": 0.5},
    {"symbol": "AMZN", "company_name": "Amazon.com Inc.", "relevance": 0.3}
  ],
  "overall_sentiment": 0.5
}
```
After parse: `tickers = [AAPL(0.95), TSLA(0.9), GOOG(0.7)]`, dropped = `[NVDA(cap), AMZN(cap)]`.

### Example 3: LLM Response With Invalid Ticker
```json
{
  "entities": [...],
  "tickers": [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.95},
    {"symbol": "XYZFAKE", "company_name": "Fake Corp", "relevance": 0.8}
  ],
  "overall_sentiment": 0.3
}
```
After validation: `tickers = [AAPL(0.95)]`, dropped = `[XYZFAKE(invalid)]`.

### Example 4: CLI Output
```
============================================================
  Seed Injection Complete
============================================================
  Cycle ID:          abc-123-def
  Overall Sentiment: +0.30
  Parse Quality:     Tier 1 (direct JSON)
  Entities:          3
  Tickers:           2

  Name                      Type       Relevance  Sentiment
  ------------------------- ---------- ---------- ----------
  Apple                     company          0.95      +0.70
  Tesla                     company          0.90      -0.30
  Electric Vehicles         sector           0.60      +0.40

  Symbol     Company                        Relevance
  ---------- ------------------------------ ----------
  AAPL       Apple Inc.                           0.95
  TSLA       Tesla Inc.                           0.90

  Dropped Tickers:
  ----------------------------------------
  XYZFAKE    (reason: invalid)
============================================================
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24+ |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_parsing.py tests/test_seed.py tests/test_ticker_validator.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TICK-01 | Orchestrator extracts tickers alongside entities in single call | unit (parsing) | `uv run pytest tests/test_parsing.py::test_seed_parse_with_tickers_tier1 -x` | Wave 0 |
| TICK-01 | ExtractedTicker model validates correctly | unit (model) | `uv run pytest tests/test_seed.py::test_extracted_ticker_valid -x` | Wave 0 |
| TICK-02 | Invalid tickers rejected by SEC validator | unit (validator) | `uv run pytest tests/test_ticker_validator.py::test_validate_invalid_symbol -x` | Wave 0 |
| TICK-02 | SEC file loading produces correct ticker set | unit (validator) | `uv run pytest tests/test_ticker_validator.py::test_load_ticker_set -x` | Wave 0 |
| TICK-03 | More than 3 tickers capped to top 3 by relevance | unit (parsing) | `uv run pytest tests/test_parsing.py::test_seed_parse_ticker_cap -x` | Wave 0 |
| TICK-03 | Dropped tickers include reason label | unit (parsing) | `uv run pytest tests/test_parsing.py::test_seed_parse_dropped_reasons -x` | Wave 0 |
| TICK-03 | CLI displays kept and dropped tickers | unit (cli) | `uv run pytest tests/test_cli.py::test_injection_summary_tickers -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_parsing.py tests/test_seed.py tests/test_ticker_validator.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_ticker_validator.py` -- NEW: covers TICK-02 (SEC loading, validation, download mock)
- [ ] `tests/test_parsing.py` additions -- covers TICK-01 (tickers in seed parse), TICK-03 (cap logic, dropped reasons)
- [ ] `tests/test_seed.py` additions -- covers TICK-01 (ExtractedTicker model, SeedEvent with tickers)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| httpx | SEC file download | Yes | 0.28.1 | -- |
| structlog | Logging | Yes | (in deps) | -- |
| pydantic | ExtractedTicker model | Yes | (in deps) | -- |
| Neo4j | Cycle node tickers property | Yes (Docker) | 5.x | -- |
| SEC CDN | company_tickers.json | External | -- | Bundle a snapshot (not recommended) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- SEC CDN availability: If SEC CDN is down during first run, the download will fail with a clear error. User can retry or manually place the file. This is acceptable for a one-time setup step.

## Open Questions

1. **SEC User-Agent email address**
   - What we know: SEC requires a contact email in the User-Agent header
   - What's unclear: Whether `admin@alphaswarm.local` is acceptable or if SEC validates the domain
   - Recommendation: Use a placeholder email. SEC does not validate -- the header is for abuse contact purposes only. Any non-empty email format works.

2. **CLI subcommand `setup-data` vs auto-download only**
   - What we know: D-08 says "exposed as a CLI utility or auto-triggered on first inject run"
   - Recommendation: Implement auto-download only in Phase 16. A dedicated `setup-data` subcommand adds CLI complexity with minimal value -- auto-download on first use is simpler and covers the common case. Can add the subcommand in a future phase if users request explicit data management.

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/seed.py` -- ORCHESTRATOR_SYSTEM_PROMPT, inject_seed() current implementation
- `src/alphaswarm/types.py` -- SeedEntity, SeedEvent, ParsedSeedResult models
- `src/alphaswarm/parsing.py` -- _try_parse_seed_json(), parse_seed_event() 3-tier fallback
- `src/alphaswarm/graph.py` -- create_cycle_with_seed_event(), _create_cycle_with_entities_tx() Cypher
- `src/alphaswarm/cli.py` -- _print_injection_summary() display format
- `.planning/phases/16-ticker-extraction/16-CONTEXT.md` -- all locked decisions

### Secondary (MEDIUM confidence)
- [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) -- company_tickers.json endpoint
- [The Full Stack Accountant - Intro to EDGAR](https://www.thefullstackaccountant.com/blog/intro-to-edgar) -- file schema documentation
- [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) -- User-Agent header requirements

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official SEC documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all tools already in pyproject.toml
- Architecture: HIGH -- direct extension of established patterns (SeedEntity, _try_parse_seed_json, entity table display)
- Pitfalls: HIGH -- SEC User-Agent requirement verified via web search + official docs; all other pitfalls derived from direct code inspection
- Type model: HIGH -- follows exact SeedEntity pattern, backward compatibility ensured via default fields

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable -- SEC CDN endpoint unchanged for years, codebase patterns well-established)
