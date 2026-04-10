# Phase 25: Portfolio Impact Analysis - Research

**Researched:** 2026-04-09
**Domain:** CSV parsing, ticker-entity bridge, ReACT tool extension, Jinja2 template rendering
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**CSV Parsing**
- D-01: Target raw Schwab export format (`Individual-Positions-*.csv`) — not simplified `holdings.csv`
- D-02: Skip the 2 metadata rows at the top; row 3 is the actual column header row
- D-03: Filter to `Asset Type == "Equity"` rows only — ETFs and money market rows excluded; they appear as coverage gaps
- D-04: Parse currency-formatted values (e.g., `"$26,416.56 "`) by stripping `$`, `,`, and spaces before converting to float
- D-05: Holdings never written to Neo4j or disk — loaded into in-memory dict keyed by ticker symbol for report run duration only

**Ticker-Entity Bridge**
- D-06: Use a static `TICKER_ENTITY_MAP` constant — dict mapping ticker symbols to one or more canonical entity name substrings
- D-07: Match performed against `read_entity_impact()` results — case-insensitive substring match on entity_name
- D-08: Tickers not in the map or not found in entity_impact results are coverage gaps — ETFs always gaps
- D-09: TICKER_ENTITY_MAP pre-populated for all 25 equities currently in Schwab portfolio

**LLM Narrative via ReACT Tool**
- D-10: New `portfolio_impact` tool added to ReACT engine's `tools` dict in `_handle_report()` — only when `--portfolio` is provided
- D-11: Tool returns structured data: `matched_tickers` (list of `{ticker, shares, market_value, signal, confidence, entity_name}`), `gap_tickers` (list of `{ticker, shares, market_value}`), and `coverage_summary` stats
- D-12: Orchestrator's ReACT reasoning loop synthesizes narrative naturally — narrative is part of FINAL ANSWER synthesis, not a separate LLM call
- D-13: New Jinja2 template `10_portfolio_impact.j2` renders structured data as formatted table in markdown; `TOOL_TO_TEMPLATE` and `SECTION_ORDER` updated — guarded on presence in observations

**CLI Integration**
- D-14: `--portfolio` flag added to existing `report` argparse subparser — accepts a path string
- D-15: Portfolio parsing happens inside `_handle_report()` before engine run — parsed holdings dict captured by tool closure
- D-16: If `--portfolio` not provided or path not found, `_handle_report()` behaves identically to current — no regression

### Claude's Discretion
- Exact TICKER_ENTITY_MAP canonical name strings (as long as they match Neo4j entity naming)
- Template layout for the portfolio section (table structure, column order)
- Coverage gap display (table vs bullet list)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PORTFOLIO-01 | User can point CLI at a Schwab CSV file; system parses holdings without persisting to Neo4j or disk | CSV parsing pattern documented; in-memory dict approach confirmed with Python `csv` stdlib |
| PORTFOLIO-02 | Post-simulation output shows held tickers with swarm consensus signals mapped to user positions | `read_entity_impact()` return schema confirmed; case-insensitive substring match design verified |
| PORTFOLIO-03 | Held tickers not covered by simulation are explicitly listed as coverage gaps | Coverage gap logic from TICKER_ENTITY_MAP + entity_impact intersection fully mapped |
| PORTFOLIO-04 | LLM-generated narrative compares swarm consensus vs user positions in natural language, in both markdown and HTML reports | ReACT tool extension pattern confirmed; Jinja2 template pattern (#10) and `assemble_html()` integration point verified |
</phase_requirements>

---

## Summary

Phase 25 adds portfolio-awareness to the existing post-simulation report pipeline. The core work is three tightly-scoped additions: (1) a CSV parser that reads Schwab's raw export format into memory, (2) a `portfolio_impact` tool function added to the ReACT tool registry that bridges parsed holdings against `read_entity_impact()` results, and (3) a new Jinja2 template (`10_portfolio_impact.j2`) that renders matched and gap tickers into the markdown and HTML reports.

The design is deliberately side-effect-free: holdings are never written to Neo4j or any file. The ReACT loop naturally incorporates the `portfolio_impact` tool observation into its FINAL ANSWER narrative without any extra LLM call. The entire phase is an extension of the existing pattern — it follows every convention already established in `report.py`, `cli.py`, and the templates directory.

The Schwab CSV has been read directly and its exact format is documented below. The code is well-understood from reading the canonical reference files; confidence in all integration points is HIGH.

**Primary recommendation:** Implement in one plan: CSV parser module + TICKER_ENTITY_MAP constant + portfolio_impact tool function + 10_portfolio_impact.j2 template + CLI --portfolio arg + HTML section + tests. The work is sequential but small enough to fit in a single plan.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `csv` (stdlib) | Python 3.11 stdlib | Parse Schwab CSV with `DictReader` | Already available, handles quoted fields with embedded commas and `$` chars natively |
| `io.StringIO` (stdlib) | Python 3.11 stdlib | Feed pre-processed CSV text (after skipping 2 header rows) to `DictReader` | Standard pattern for skipping header rows |
| `jinja2` | Already installed (report.py uses it) | Template `10_portfolio_impact.j2` | Same Jinja2 `Environment` already in `ReportAssembler.__init__` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiofiles` | Already installed | Async CSV file read (for consistency with async handler) | Inside `_handle_report()` where all I/O is async |
| `pathlib.Path` | stdlib | Validate `--portfolio` path existence before parsing | Already used in `_handle_report()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `csv.DictReader` | `pandas` | pandas is NOT in the project stack (no `uv add pandas`), and is overkill for 30-row CSV; `csv.DictReader` is zero-dependency |

**Installation:** No new packages needed. All dependencies are already installed.

---

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
├── portfolio.py          # parse_schwab_csv(), TICKER_ENTITY_MAP, build_portfolio_impact()
├── templates/report/
│   └── 10_portfolio_impact.j2   # Jinja2 markdown template
├── cli.py                # --portfolio arg + _handle_report() integration
└── report.py             # TOOL_TO_TEMPLATE + SECTION_ORDER + assemble_html() portfolio slot
```

New module: `src/alphaswarm/portfolio.py` isolates all CSV and bridge logic for testability. This follows the established pattern (`graph.py`, `charts.py`, `report.py` are all top-level modules).

### Pattern 1: Schwab CSV Parsing

**What:** `parse_schwab_csv(path: Path) -> dict[str, dict]` reads the file, skips 2 metadata rows, uses `csv.DictReader` on remainder, filters `Asset Type == "Equity"`, strips currency formatting, returns dict keyed by ticker.

**When to use:** Called once at start of `_handle_report()` when `--portfolio` is provided.

**Actual CSV structure (verified from file):**

```
Row 1: "Positions for account Individual  as of 03:47 PM ET, 2026/04/09",,...
Row 2: (empty)
Row 3: Symbol,Description,Qty (Quantity),Price,...,Asset Type   <- actual headers
Row 4+: AAPL,APPLE INC,101.3071,...,Equity
...
Row N: Positions Total,,--,...,--       <- sentinel row to skip
Row N+1: Cash & Cash Investments,...   <- sentinel row to skip
```

Key columns:
- `Symbol` — ticker (e.g., `"AAPL"`)
- `Qty (Quantity)` — shares (plain float, may contain `,` for thousands: LPL has `"1,000"`)
- `Mkt Val (Market Value)` — market value (format: `"$26,416.56 "` with trailing space)
- `Asset Type` — `"Equity"` | `"ETFs & Closed End Funds"` | `"Cash and Money Market"`

**Currency stripping:** `float(value.strip().replace("$","").replace(",",""))` — handles trailing spaces, `$`, and comma-thousands separators. For negative values like `($4,472.00)` the parens indicate negative; strip `(` and `)` as well.

**Sentinel rows to skip:** Rows where `Symbol` is `"Positions Total"`, `"Cash & Cash Investments"`, or empty string. Also skip rows where `Asset Type != "Equity"`.

**Example:**
```python
# Source: verified from Schwab/Individual-Positions-2026-04-09-154713.csv
import csv, io
from pathlib import Path

def parse_schwab_csv(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Skip rows 0 and 1 (metadata + blank), feed from row 2 onward
    body = "\n".join(lines[2:])
    reader = csv.DictReader(io.StringIO(body))
    holdings: dict[str, dict] = {}
    for row in reader:
        symbol = row.get("Symbol", "").strip()
        asset_type = row.get("Asset Type", "").strip()
        if not symbol or asset_type != "Equity":
            continue
        if symbol in ("Positions Total", "Cash & Cash Investments"):
            continue
        raw_qty = row.get("Qty (Quantity)", "0").strip().replace(",", "")
        raw_mkt_val = row.get("Mkt Val (Market Value)", "$0").strip()
        raw_mkt_val = raw_mkt_val.replace("$","").replace(",","").replace("(", "-").replace(")", "").strip()
        holdings[symbol] = {
            "ticker": symbol,
            "shares": float(raw_qty),
            "market_value": float(raw_mkt_val),
        }
    return holdings
```

### Pattern 2: Portfolio Impact Tool Function

**What:** Closure that captures `holdings: dict[str, dict]` and `gm` (GraphStateManager). When called by ReACT engine, fetches `entity_impact` results and performs ticker-to-entity bridge matching.

**When to use:** Added to `tools` dict in `_handle_report()` only when `--portfolio` arg is provided.

**Example:**
```python
# Source: cli.py _handle_report() pattern (lines 685-694)
# All existing tools are lambdas capturing gm and cycle_id

async def _portfolio_impact_tool(**kw: object) -> dict:
    cycle = kw.get("cycle_id", cycle_id)
    entity_results = await gm.read_entity_impact(str(cycle))
    # Build name -> entity dict for fast lookup
    entity_by_name = {e["entity_name"].lower(): e for e in entity_results}

    matched = []
    gaps = []
    for ticker, pos in holdings.items():
        entity_substrings = TICKER_ENTITY_MAP.get(ticker, [])
        found_entity = None
        for substring in entity_substrings:
            sub_lower = substring.lower()
            for entity_name_lower, entity_data in entity_by_name.items():
                if sub_lower in entity_name_lower:
                    found_entity = entity_data
                    break
            if found_entity:
                break
        if found_entity:
            # Derive majority signal from buy/sell/hold counts
            counts = {
                "BUY": found_entity["buy_mentions"],
                "SELL": found_entity["sell_mentions"],
                "HOLD": found_entity["hold_mentions"],
            }
            majority_signal = max(counts, key=counts.get)
            total = sum(counts.values()) or 1
            majority_pct = counts[majority_signal] / total
            matched.append({
                "ticker": ticker,
                "shares": pos["shares"],
                "market_value": pos["market_value"],
                "signal": majority_signal,
                "confidence": round(majority_pct, 3),
                "entity_name": found_entity["entity_name"],
                "avg_sentiment": round(found_entity["avg_sentiment"], 3),
                "mention_count": found_entity["mention_count"],
            })
        else:
            gaps.append({
                "ticker": ticker,
                "shares": pos["shares"],
                "market_value": pos["market_value"],
            })

    covered = len(matched)
    total_holdings = len(holdings)
    return {
        "matched_tickers": matched,
        "gap_tickers": gaps,
        "coverage_summary": {
            "covered": covered,
            "total_equity_holdings": total_holdings,
            "coverage_pct": round(covered / total_holdings * 100, 1) if total_holdings else 0.0,
        },
    }

tools["portfolio_impact"] = _portfolio_impact_tool
```

### Pattern 3: Jinja2 Template (10_portfolio_impact.j2)

**What:** Markdown template rendering matched tickers table and coverage gap section. Follows the exact same pattern as `07_entity_impact.j2`.

**Template variable:** `data` is the full dict returned by the tool (`matched_tickers`, `gap_tickers`, `coverage_summary`).

**Example sketch:**
```jinja
## Portfolio Impact

**Coverage:** {{ data.coverage_summary.covered }}/{{ data.coverage_summary.total_equity_holdings }} equity holdings covered ({{ data.coverage_summary.coverage_pct }}%)

### Matched Positions

| Ticker | Shares | Market Value | Swarm Signal | Confidence | Entity | Avg Sentiment |
|--------|--------|--------------|-------------|------------|--------|---------------|
{% for t in data.matched_tickers %}
| {{ t.ticker }} | {{ "%.4f"|format(t.shares) }} | ${{ "%.2f"|format(t.market_value) }} | {{ t.signal }} | {{ "%.1f"|format(t.confidence * 100) }}% | {{ t.entity_name }} | {{ "%.2f"|format(t.avg_sentiment) }} |
{% endfor %}

### Coverage Gaps

{% if data.gap_tickers %}
The following equity holdings had no corresponding entity in this simulation run:

| Ticker | Shares | Market Value |
|--------|--------|--------------|
{% for g in data.gap_tickers %}
| {{ g.ticker }} | {{ "%.4f"|format(g.shares) }} | ${{ "%.2f"|format(g.market_value) }} |
{% endfor %}
{% else %}
All equity holdings have swarm coverage.
{% endif %}
```

### Pattern 4: HTML Section Extension

**What:** Add portfolio section block directly in `report.html.j2` after Market Context — checking `sections.get("portfolio_impact")`. No changes to `assemble_html()` signature needed; `sections` dict already contains all tool results.

**Where in HTML template:** After the Market Context block (line ~291), before `</body>`. Guard with `{% if sections.get("portfolio_impact") %}`.

**Rendering matched tickers in HTML:** Use the same `signal-buy`/`signal-sell`/`signal-hold` CSS classes already present. No new CSS needed.

### Pattern 5: TICKER_ENTITY_MAP

**What:** Module-level constant in `portfolio.py`. Maps ticker → list of name substrings to look for in `entity_impact` results. Substrings should be conservative (unambiguous company name fragments).

**All 25 equities to map (verified from CSV):**

| Ticker | Company (from CSV) | Suggested substring(s) |
|--------|--------------------|------------------------|
| AAPL | APPLE INC | `["Apple"]` |
| AMZN | AMAZON.COM INC | `["Amazon"]` |
| ARM | ARM HLDGS PLC | `["Arm", "ARM"]` |
| ASML | ASML HLDG N V | `["ASML"]` |
| AVGO | BROADCOM INC | `["Broadcom"]` |
| BYDDY | BYD CO LTD | `["BYD"]` |
| COHR | COHERENT CORP | `["Coherent"]` |
| DBX | DROPBOX INC | `["Dropbox"]` |
| HIMS | HIMS & HERS HEALTH | `["Hims", "Hims & Hers"]` |
| HON | HONEYWELL INTL | `["Honeywell"]` |
| ISRG | INTUITIVE SURGICAL | `["Intuitive Surgical"]` |
| LPL | LG DISPLAY CO | `["LG Display"]` |
| MRVL | MARVELL TECHNOLOGY | `["Marvell"]` |
| NIO | NIO INC | `["Nio", "NIO"]` |
| NKE | NIKE INC | `["Nike"]` |
| NVDA | NVIDIA CORP | `["NVIDIA", "Nvidia"]` |
| PLTR | PALANTIR TECHNOLOGIES | `["Palantir"]` |
| PYPL | PAYPAL HLDGS | `["PayPal", "Paypal"]` |
| SCHW | CHARLES SCHWAB | `["Schwab", "Charles Schwab"]` |
| SOFI | SOFI TECHNOLOGIES | `["SoFi", "Sofi"]` |
| TLN | TALEN ENERGY | `["Talen"]` |
| TSLA | TESLA INC | `["Tesla"]` |
| TSM | TAIWAN SEMICONDUCTOR | `["TSMC", "Taiwan Semiconductor"]` |
| VRT | VERTIV HLDGS | `["Vertiv"]` |
| VST | VISTRA CORP | `["Vistra"]` |

**Note on discretion:** Exact strings are Claude's discretion per CONTEXT.md. The above entries are reasonable starting points; the planner should finalize based on what names the simulation actually produces in entity_impact results.

### Anti-Patterns to Avoid

- **Reading CSV synchronously inside async handler without aiofiles:** `_handle_report()` is fully async; use `aiofiles` for file read or `asyncio.to_thread(path.read_text)` to avoid blocking event loop.
- **Writing holdings to Neo4j or a temp file:** Explicitly forbidden by D-05. All state stays in-memory in the `holdings` dict for the duration of `_handle_report()`.
- **Calling `read_entity_impact()` inside the tool when it was already called by the engine:** The engine may call `entity_impact` tool before `portfolio_impact`; `portfolio_impact` must call `gm.read_entity_impact()` independently — it cannot rely on what the engine observed. This is intentional; the call is fast.
- **Using pandas for CSV:** Not in the stack. `csv.DictReader` handles all cases.
- **Hardcoding summary row detection by row number:** Detect sentinel rows by `Symbol` value (e.g., `"Positions Total"`) not by line number — file may grow as positions are added.
- **autoescape=False for the HTML template:** `report.py`'s `assemble_html()` uses a separate `html_env` with `autoescape=True`. Portfolio data flowing into the HTML section goes through autoescaping — SVG strings are `|safe`-filtered at call site in the HTML template, not in Python.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Quoted CSV with commas inside values | Manual string splitting | `csv.DictReader` | Values like `"$26,416.56 "` have commas inside quotes; stdlib handles RFC 4180 correctly |
| Currency value parsing | Regex | String `.replace()` chain + `float()` | Simple, readable, handles all cases in the actual file |
| Jinja2 environment for markdown template | New `Environment()` in portfolio.py | Existing `ReportAssembler._env` | `ReportAssembler` already constructs the environment; add entry to `TOOL_TO_TEMPLATE` and `SECTION_ORDER` |

---

## Common Pitfalls

### Pitfall 1: Negative market values in parentheses notation
**What goes wrong:** `($2,350.33)` parses as a string — `float()` will raise `ValueError`.
**Why it happens:** Schwab uses `(value)` for negative numbers in some columns (e.g., `Day Chng $`). The `Mkt Val` column can also go negative for leveraged positions though not present in the current CSV.
**How to avoid:** Strip `(` and `)` and replace with `-` prefix: `value.replace("(", "-").replace(")", "")`.
**Warning signs:** Rows with Day Chng negative already have parens: e.g., `($4,472.00)` for PLTR day change.

### Pitfall 2: Trailing space in currency strings
**What goes wrong:** `"$26,416.56 "` — note the trailing space after the closing quote. `float("$26,416.56 ")` fails.
**Why it happens:** Schwab CSV has a trailing space inside quoted fields. Visible in every Mkt Val column of the actual file.
**How to avoid:** `.strip()` before `.replace()` chain. Always strip first.
**Warning signs:** Unit test with exact Schwab file values will catch this immediately.

### Pitfall 3: Qty (Quantity) has commas for large share counts
**What goes wrong:** LPL has `"1,000"` shares — `float("1,000")` raises `ValueError`.
**Why it happens:** Schwab formats quantities with thousands separators when >= 1000.
**How to avoid:** `.replace(",", "")` before `float()`.
**Warning signs:** LPL row in the test CSV.

### Pitfall 4: REACT system prompt doesn't mention `portfolio_impact` tool
**What goes wrong:** LLM doesn't know `portfolio_impact` exists; it never calls it; no portfolio section appears in the report.
**Why it happens:** `REACT_SYSTEM_PROMPT` in `report.py` hardcodes the available tool list (lines 39-47). Adding the tool to the `tools` dict is not enough.
**How to avoid:** When `--portfolio` is provided, either (a) dynamically append `"- portfolio_impact: ..."` to the system prompt, or (b) inject a user message after the initial prompt listing the additional tool. Approach (a) is simpler.
**Warning signs:** Report generates without portfolio section even though `--portfolio` was provided.

### Pitfall 5: `SECTION_ORDER` index 9 conflicts with existing or gaps tool
**What goes wrong:** Template named `10_portfolio_impact.j2` but `SECTION_ORDER` position misaligned.
**Why it happens:** `SECTION_ORDER` currently has 8 entries (indices 0-7). Portfolio_impact is the 9th entry (list index 8). The template file `10_` prefix is cosmetic naming only — the mapping is `TOOL_TO_TEMPLATE["portfolio_impact"] = "10_portfolio_impact.j2"`.
**How to avoid:** Append to both `SECTION_ORDER` and `TOOL_TO_TEMPLATE` — don't insert mid-list.
**Warning signs:** Section silently absent from assembled report.

### Pitfall 6: ETF tickers appearing as equity gaps (expected, not a bug)
**What goes wrong:** Treating ETF coverage gap entries as a parser bug.
**Why it happens:** D-03 filters to `Asset Type == "Equity"` only. CHAT, CQQQ, QQQ, SPY, WTAI are ETFs and will never appear in `holdings` dict — they're excluded at parse time. If somehow an ETF slips through via TICKER_ENTITY_MAP lookup, it correctly appears as a gap.
**How to avoid:** Document in template output that ETF gaps are expected. Distinguish in template: the gap list caption should note "Equities with no simulation coverage."
**Warning signs:** Nothing — this is correct behavior per D-08.

---

## Code Examples

### CSV parse with exact Schwab field names
```python
# Source: verified directly from Schwab/Individual-Positions-2026-04-09-154713.csv
COLUMN_SYMBOL = "Symbol"
COLUMN_QTY = "Qty (Quantity)"
COLUMN_MKT_VAL = "Mkt Val (Market Value)"
COLUMN_ASSET_TYPE = "Asset Type"

# Sentinel symbol values that indicate summary/footer rows
_SENTINEL_SYMBOLS = frozenset({"Positions Total", "Cash & Cash Investments", ""})
```

### Tool closure pattern (matches existing style in cli.py lines 685-694)
```python
# Source: existing _handle_report() in cli.py
# Existing tools are lambdas; portfolio_impact can be an inner async def
if portfolio_path is not None and portfolio_path.exists():
    holdings = await _parse_portfolio(portfolio_path)  # async file read

    async def _portfolio_impact(**kw: object) -> dict:  # type: ignore[return]
        return await _build_portfolio_impact(holdings, gm, str(kw.get("cycle_id", cycle_id)))

    tools["portfolio_impact"] = _portfolio_impact
    # Also inject tool description into system prompt for this run
```

### `TOOL_TO_TEMPLATE` and `SECTION_ORDER` additions (report.py)
```python
# Source: report.py lines 222-243 — append to existing structures
TOOL_TO_TEMPLATE: dict[str, str] = {
    # ... existing 8 entries ...
    "portfolio_impact": "10_portfolio_impact.j2",
}

SECTION_ORDER: list[str] = [
    # ... existing 8 entries ...
    "portfolio_impact",
]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No portfolio awareness | Post-sim report only shows simulation data | — | Phase 25 adds personal relevance layer |
| Static `assemble_html()` signature | `market_context_data` param already added (Phase 24) | Phase 24 | Portfolio HTML section can be added without signature change |

---

## Open Questions

1. **Dynamic system prompt injection for `portfolio_impact` tool**
   - What we know: `REACT_SYSTEM_PROMPT` is a module-level constant. LLM must know the tool name to call it.
   - What's unclear: Whether to build the system prompt string dynamically in `_handle_report()` or add a second user message listing optional tools.
   - Recommendation: Build system prompt as a formatted string that conditionally appends `"- portfolio_impact: ..."` when `--portfolio` is provided. This keeps the engine stateless and clean.

2. **`coverage_summary.confidence` vs. individual-ticker confidence semantics**
   - What we know: `read_entity_impact()` returns `buy_mentions + sell_mentions + hold_mentions` counts, not a per-agent confidence score.
   - What's unclear: CONTEXT.md D-11 says `confidence` in matched_tickers. This is best computed as `majority_count / total_mentions` (percent agreement), not the raw Ollama confidence field.
   - Recommendation: Use `majority_pct = max(counts.values()) / sum(counts.values())` as the confidence proxy. Label it "Agreement" in the template for clarity.

3. **Async CSV read — aiofiles vs `asyncio.to_thread`**
   - What we know: `_handle_report()` is async; blocking `Path.read_text()` would block the event loop.
   - What's unclear: Whether aiofiles is necessary for a 30-row file.
   - Recommendation: Use `asyncio.to_thread(path.read_text, encoding="utf-8")` — simpler than aiofiles for this case. aiofiles is already installed if needed.

---

## Environment Availability

Step 2.6: SKIPPED (no new external dependencies — all required libraries are stdlib or already in the project dependency set).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 + pytest-asyncio |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_portfolio.py -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PORTFOLIO-01 | `parse_schwab_csv()` returns equity-only dict with correct ticker keys | unit | `uv run pytest tests/test_portfolio.py::TestParseSchwabCsv -x` | Wave 0 |
| PORTFOLIO-01 | Currency values parsed correctly (strip `$`, `,`, spaces, parens) | unit | `uv run pytest tests/test_portfolio.py::TestCurrencyParsing -x` | Wave 0 |
| PORTFOLIO-01 | Holdings dict is not written to any file or Neo4j | unit | `uv run pytest tests/test_portfolio.py::TestNoPersistence -x` | Wave 0 |
| PORTFOLIO-02 | `build_portfolio_impact()` returns matched tickers with correct signals | unit | `uv run pytest tests/test_portfolio.py::TestBuildPortfolioImpact -x` | Wave 0 |
| PORTFOLIO-02 | Case-insensitive substring match works for entity names | unit | `uv run pytest tests/test_portfolio.py::TestTickerEntityBridge -x` | Wave 0 |
| PORTFOLIO-03 | Tickers without entity match appear in `gap_tickers` | unit | `uv run pytest tests/test_portfolio.py::TestCoverageGaps -x` | Wave 0 |
| PORTFOLIO-03 | `coverage_summary` counts are correct | unit | `uv run pytest tests/test_portfolio.py::TestCoverageSummary -x` | Wave 0 |
| PORTFOLIO-04 | `10_portfolio_impact.j2` renders matched table with all columns | unit | `uv run pytest tests/test_portfolio.py::TestPortfolioTemplate -x` | Wave 0 |
| PORTFOLIO-04 | `10_portfolio_impact.j2` renders gap section | unit | `uv run pytest tests/test_portfolio.py::TestPortfolioTemplateGaps -x` | Wave 0 |
| PORTFOLIO-04 | `ReportAssembler.assemble()` includes portfolio section when observation present | unit | `uv run pytest tests/test_portfolio.py::TestAssemblerIntegration -x` | Wave 0 |
| PORTFOLIO-04 | HTML report includes portfolio section when `portfolio_impact` in observations | unit | `uv run pytest tests/test_portfolio.py::TestHtmlPortfolioSection -x` | Wave 0 |
| All | Existing 33 report tests still pass (regression) | unit | `uv run pytest tests/test_report.py -q` | ✅ exists |
| D-16 | `_handle_report()` without `--portfolio` produces identical output | integration | `uv run pytest tests/test_portfolio.py::TestNoRegressionWithoutFlag -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_portfolio.py -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_portfolio.py` — covers PORTFOLIO-01, 02, 03, 04 (all test classes above)

*(Existing `tests/test_report.py` covers the base assembly — no changes needed to it. Existing 33 tests confirmed green.)*

---

## Sources

### Primary (HIGH confidence)
- Direct file read: `src/alphaswarm/report.py` — full ReportEngine, ReportAssembler, TOOL_TO_TEMPLATE, SECTION_ORDER, assemble_html() implementation
- Direct file read: `src/alphaswarm/cli.py` (lines 633-818) — `_handle_report()` full implementation, argparse subparser definition
- Direct file read: `src/alphaswarm/graph.py` (lines 1359-1402) — `read_entity_impact()` return schema
- Direct file read: `src/alphaswarm/charts.py` (lines 116-143) — `render_ticker_consensus()` interface
- Direct file read: `src/alphaswarm/templates/report/report.html.j2` — full HTML template structure and CSS
- Direct file read: `Schwab/Individual-Positions-2026-04-09-154713.csv` — canonical Schwab export; all 36 rows including metadata header, equity rows, ETF rows, summary rows

### Secondary (MEDIUM confidence)
- Direct file read: `tests/test_report.py` — established test patterns for report components
- Direct file read: `tests/conftest.py` — shared fixtures and test conventions

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified as already installed or stdlib; no new installs needed
- Architecture patterns: HIGH — all integration points read directly from source; no inference required
- CSV parsing: HIGH — actual Schwab CSV file read character-by-character; all edge cases documented from real data
- Pitfalls: HIGH — discovered from reading actual file content (parens notation, trailing spaces, thousands commas) plus code reading (REACT_SYSTEM_PROMPT gap)
- Test plan: HIGH — follows exact patterns in `test_report.py`

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (stable internal codebase; no fast-moving external dependencies)
