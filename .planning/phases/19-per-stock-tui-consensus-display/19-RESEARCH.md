# Phase 19: Per-Stock TUI Consensus Display - Research

**Researched:** 2026-04-07
**Domain:** Textual TUI widget authoring, consensus aggregation, StateStore extension
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** New right-side column added to `main-row` in `AlphaSwarmApp.compose()`. Layout: `grid-container (30w) | rationale sidebar (1fr) | ticker consensus panel (width=44)`. Always rendered (shows "Awaiting..." per round during live execution, updates after each round).
- **D-02:** `BracketPanel` stays in `bottom-row` unchanged. New `TickerConsensusPanel` is independent.
- **D-03:** Ticker consensus updates after each round (R1, R2, R3), not only at COMPLETE. After each round in `simulation.py`, compute and push to `StateStore`.
- **D-04:** Round label per ticker: `"R1"`, `"R2"`, `"R3"`. No special "Final" label.
- **D-05:** New frozen dataclass `TickerConsensus` in `state.py` with fields: `ticker`, `round_num`, `weighted_signal`, `weighted_score`, `majority_signal`, `majority_pct`, `bracket_breakdown: tuple[BracketSummary, ...]`.
- **D-06:** `StateSnapshot` gains `ticker_consensus: tuple[TickerConsensus, ...] = ()`.
- **D-07:** `StateStore` gains `async def set_ticker_consensus(self, consensus: tuple[TickerConsensus, ...]) -> None`.
- **D-08:** `compute_ticker_consensus()` iterates `AgentDecision.ticker_decisions` grouped by ticker. Majority vote = dominant direction by count. Confidence-weighted = direction with highest sum of `decision.confidence × influence_weights.get(agent_id, persona.influence_weight_base)`. Bracket breakdown reuses `BracketSummary`, filtered to agents with a `TickerDecision` for that ticker.
- **D-09:** Agents with empty `ticker_decisions` (PARSE_ERROR fallback) excluded. `influence_weights` from current round; fallback to `persona.influence_weight_base` if agent absent from dict.
- **D-10:** New `TickerConsensusPanel(Widget)` in `tui.py`. TCSS: `width: 44`, `height: 100%`, `border-left: solid $secondary`.
- **D-11:** Header line per ticker: `AAPL  BUY  w=0.74  (68% majority)  R3`. Below each ticker: 10 bracket mini-bars, BAR_WIDTH=12. Bar color = dominant signal for that bracket × that ticker.
- **D-12:** ~36 rows for 3 tickers. Panel uses `overflow-y: auto` TCSS. Vertical scroll is the correct approach — confirmed native Textual support.
- **D-13:** No tickers in snapshot: panel shows `"No tickers\nextracted"` in `#78909C` gray.
- **D-14:** `_poll_snapshot()` diffs `snapshot.ticker_consensus != self._prev_ticker_consensus` to trigger `TickerConsensusPanel.update_consensus(...)`.

### Claude's Discretion

- Exact TCSS scroll implementation (ScrollView vs overflow property) — research confirms `overflow-y: auto` on `Widget` is correct; `ScrollableContainer` is an alternative but adds nesting complexity not needed here.
- Whether bracket bar label uses full display name or abbreviated — full display name (matches BracketPanel pattern, BRACKET_LABEL_WIDTH=14).
- Exact round label display — `R1`/`R2`/`R3` (compact, per D-04 and UI-SPEC).
- Test fixture approach — real `TickerConsensus` instances (matches test_state.py and test_tui.py pattern of constructing real dataclasses).
- Whether `compute_ticker_consensus()` lives in `simulation.py` or `consensus.py` — recommend `simulation.py` (same module as `compute_bracket_summaries()`, keeps pattern symmetry, avoids new module).

### Deferred Ideas (OUT OF SCOPE)

- Weighted score formula validation (confidence × influence_weight² tuning)
- Click-to-drill-down on ticker rows
- Historical round comparison / sparklines across rounds
- `expected_return_pct` and `time_horizon` display (Phase 20)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DTUI-01 | TUI displays per-ticker consensus panel: ticker symbol, aggregate signal (BUY/SELL/HOLD), aggregate confidence, vote distribution | `TickerConsensusPanel.render()` using `TickerConsensus.weighted_signal`, `weighted_score`, `majority_pct`; all visible in header line format per UI-SPEC |
| DTUI-02 | Consensus aggregation uses confidence-weighted voting (`confidence × influence_weight`) alongside discrete majority vote; both visible in display | `compute_ticker_consensus()` computes both; display format `AAPL  BUY  w=0.74  (68% majority)  R3` shows both inline |
| DTUI-03 | Per-ticker bracket breakdown showing which brackets are bullish/bearish, making inter-bracket disagreement visually clear | `TickerConsensus.bracket_breakdown` (per-ticker `BracketSummary` tuple) rendered as 10 mini-bars per ticker, each color-coded to dominant signal |
</phase_requirements>

---

## Summary

Phase 19 is a pure display/wiring phase. The simulation engine already produces `AgentDecision.ticker_decisions` (Phase 18), `influence_weights` are already computed after each round, and `StateStore` already has the `set_bracket_summaries()` / snapshot polling pattern to mirror exactly. No new inference calls, no new Neo4j schema, no new external dependencies.

The three integration seams are: (1) `state.py` — add `TickerConsensus` dataclass, extend `StateSnapshot`, extend `StateStore`; (2) `simulation.py` — add `compute_ticker_consensus()`, call it at the same 3 round-completion points where `set_bracket_summaries()` is called; (3) `tui.py` — add `TickerConsensusPanel` widget, wire into `compose()` as the 3rd column of `main-row`, add diff/update logic in `_poll_snapshot()`.

All architecture patterns, constants, color values, and CSS properties have been verified against the live codebase (Textual 8.1.1). The `overflow-y: auto` TCSS property is confirmed available on `Widget` instances — `RenderStyles.overflow_y` exists and Textual's `get_content_height()` correctly measures Rich Text output height to enable scroll.

**Primary recommendation:** Mirror `BracketPanel` exactly. Three files, three integration points, no new patterns.

---

## Standard Stack

### Core (already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.1.1 | TUI framework — widget authoring, TCSS, scroll | Project-mandated, already in use |
| rich | (textual dep) | `Text` renderable for `render() -> Text` pattern | Already used by `BracketPanel`, `RationaleSidebar` |
| asyncio | stdlib | Lock-guarded async writes in `StateStore` | All state writes are async per project constraint |
| structlog | (installed) | Logging inside TUI and simulation | `logger = structlog.get_logger(component="tui")` pattern already set |

### No New Dependencies

This phase adds zero new packages. All required libraries are already installed.

**Installation:** None required.

---

## Architecture Patterns

### Pattern 1: `render() -> Text` Widget (BracketPanel mirror)

**What:** `TickerConsensusPanel` extends `Widget`, overrides `render() -> Text`, holds internal state updated via `update_consensus()`, calls `self.refresh()` to trigger re-render.

**When to use:** Read-only display panel with no interaction, Rich text content, diff-triggered updates.

**Example (from existing BracketPanel at tui.py:314):**
```python
class BracketPanel(Widget):
    DEFAULT_CSS = """
    BracketPanel {
        width: 40;
        height: 100%;
        background: $panel;
        border-left: solid $secondary;
        padding: 1 1 0 1;
    }
    """
    FILL_CHAR = "\u2588"
    EMPTY_CHAR = "\u2591"
    BAR_WIDTH = 20

    def __init__(self) -> None:
        super().__init__()
        self._summaries: tuple[BracketSummary, ...] = ()

    def update_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        self._summaries = summaries
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Brackets\n", style="bold #4FC3F7")
        ...
        return text
```

**For TickerConsensusPanel:** Replace `BracketPanel` → `TickerConsensusPanel`, `width: 40` → `width: 44`, `BAR_WIDTH = 20` → `BAR_WIDTH = 12`, add `overflow-y: auto` to TCSS, rename `update_summaries` → `update_consensus`, internal field `_summaries` → `_consensus`.

### Pattern 2: StateStore Extension (set_bracket_summaries mirror)

**What:** Add `_ticker_consensus` field, `set_ticker_consensus()` async method with lock, expose in `snapshot()`.

**Example (from state.py:177):**
```python
async def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
    async with self._lock:
        self._bracket_summaries = summaries
```

**For `set_ticker_consensus`:** Identical pattern, different field name.

**`snapshot()` addition (state.py:206):** Add `ticker_consensus=self._ticker_consensus` to `StateSnapshot(...)` constructor call.

### Pattern 3: compute_bracket_summaries mirror for ticker-scoped aggregation

**What:** `compute_ticker_consensus()` takes `agent_decisions`, `personas`, `brackets`, `influence_weights`, and `tickers` list. Outer loop: per ticker. Inner loop: per-agent, filter to agents where `ticker in {td.ticker for td in decision.ticker_decisions}`.

**Key accumulator logic per ticker:**
```python
# Majority vote
majority_counts: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
# Confidence-weighted
weighted_sums: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

for agent_id, decision in agent_decisions:
    if decision.signal == SignalType.PARSE_ERROR:
        continue
    ticker_dec = next((td for td in decision.ticker_decisions if td.ticker == ticker), None)
    if ticker_dec is None:
        continue
    direction = ticker_dec.direction.value.upper()  # "BUY"/"SELL"/"HOLD"
    w = influence_weights.get(agent_id, persona_base_weight(agent_id, personas))
    majority_counts[direction] += 1
    weighted_sums[direction] += decision.confidence * w
```

**Bracket breakdown:** Call `compute_bracket_summaries()` with the filtered subset of `(agent_id, decision)` pairs (agents that have a `TickerDecision` for this ticker).

### Pattern 4: _poll_snapshot diff check (tui.py:891 mirror)

**What:** Check `snapshot.ticker_consensus != self._prev_ticker_consensus` in `_poll_snapshot()`, call `update_consensus()` only on change.

**Example (existing bracket diff at tui.py:892):**
```python
if snapshot.bracket_summaries != self._prev_bracket_summaries:
    self._bracket_panel.update_summaries(snapshot.bracket_summaries)
    self._prev_bracket_summaries = snapshot.bracket_summaries
```

**For ticker panel:** Identical structure, different field names.

### Pattern 5: compose() layout extension (tui.py:707)

**Current:**
```python
with Container(id="main-row"):
    with Container(id="grid-container"):
        ...
    yield self._rationale_sidebar
```

**New:**
```python
with Container(id="main-row"):
    with Container(id="grid-container"):
        ...
    yield self._rationale_sidebar
    yield self._ticker_consensus_panel
```

Add to CSS: `#ticker-panel { width: 44; height: 100%; background: $panel; border-left: solid $secondary; padding: 1 1 0 1; overflow-y: auto; }`.

### Recommended File Structure (changes only)

```
src/alphaswarm/
├── state.py          # +TickerConsensus dataclass, +ticker_consensus field in StateSnapshot,
│                     #  +_ticker_consensus in StateStore.__init__, +set_ticker_consensus(),
│                     #  +ticker_consensus= in snapshot()
├── simulation.py     # +compute_ticker_consensus() function, call at 3 round-complete points
└── tui.py            # +TickerConsensusPanel class, +#ticker-panel CSS, +_ticker_consensus_panel
                      #  in AlphaSwarmApp.__init__, +yield in compose(), +diff in _poll_snapshot()
```

### Anti-Patterns to Avoid

- **Circular import via new module:** Do not create `consensus.py` that imports from `state.py` and `simulation.py` simultaneously — the existing pattern already handles this by keeping `compute_bracket_summaries()` in `simulation.py`. Mirror that placement.
- **Calling `signal.value.upper()` without normalization:** `SignalType` values are lowercase (`"buy"`, `"sell"`, `"hold"`). `BracketSummary` accumulators use lowercase keys. `TickerConsensus.weighted_signal` and `majority_signal` should store uppercase (`"BUY"`, `"SELL"`, `"HOLD"`) per D-05 spec. Be explicit in the conversion.
- **Missing `overflow-y` on TickerConsensusPanel:** `BracketPanel` does not scroll (10 rows fits in any terminal). `TickerConsensusPanel` with 3 tickers produces ~36 rows and MUST declare `overflow-y: auto` in its TCSS `DEFAULT_CSS` to be scrollable. Omitting it causes content clipping with no scroll.
- **Forgetting to init `_ticker_consensus` in StateStore.__init__:** `snapshot()` references `self._ticker_consensus`. If not initialized in `__init__`, every snapshot call before `set_ticker_consensus()` raises `AttributeError`.
- **Using `can_focus = True` without scroll bindings:** The UI-SPEC specifies `can_focus = False` (passive display). If focus is accidentally enabled, it will capture keyboard events without providing scroll bindings, confusing the user.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scrollable content in Textual | Custom scroll offset tracking | `overflow-y: auto` TCSS on Widget | Textual measures `get_content_height()` from Rich Text height automatically; no virtual size management needed |
| Dominant signal calculation | Custom sort/max logic | Mirror `BracketPanel._dominant_signal()` (tui.py:371) | Already handles tie-break (BUY > SELL > HOLD), zero-count edge case, percentage computation |
| Bracket display name lookup | Dict construction in render() | `BracketSummary.display_name` already embedded in each summary | `compute_bracket_summaries()` populates display_name at construction time |
| Weighted signal normalization | Custom formula | `weighted_score = winning_sum / total_weighted_sum` | Ensures 0.0–1.0 range; matches D-05 spec |

**Key insight:** Every display primitive (bar chars, colors, signal colors, dominant-signal logic) is already defined in `BracketPanel`. Copy these constants directly — do not redefine with different values.

---

## Common Pitfalls

### Pitfall 1: Empty ticker_decisions in round data
**What goes wrong:** Some agents produce PARSE_ERROR decisions with empty `ticker_decisions = []`. If not excluded, they contribute zero entries to all tickers, silently reducing the total vote count.
**Why it happens:** `_lenient_parse_ticker_decisions()` (Phase 18) drops malformed entries, leaving an empty list rather than raising an error.
**How to avoid:** Guard `if decision.signal == SignalType.PARSE_ERROR: continue` (mirrors `compute_bracket_summaries()` pattern). Also guard `if not decision.ticker_decisions: continue`.
**Warning signs:** `majority_pct` values that seem low (e.g., 30% when most agents should agree). Check: `total valid votes` should be close to the non-PARSE_ERROR agent count.

### Pitfall 2: Division by zero in weighted_score normalization
**What goes wrong:** If all agents for a ticker are PARSE_ERROR (no valid votes), `total_weighted_sum = 0.0` — dividing to normalize causes ZeroDivisionError.
**Why it happens:** Edge case where tickers are extracted but all agents fail to produce `TickerDecision` for them (e.g., model outputs degraded).
**How to avoid:** Guard `weighted_score = winning_sum / total_weighted_sum if total_weighted_sum > 0.0 else 0.0`. Similarly guard `majority_pct` with `if total_valid_votes > 0`.
**Warning signs:** ZeroDivisionError traceback in TUI Worker, panel stuck at "Awaiting...".

### Pitfall 3: SignalType direction case mismatch
**What goes wrong:** `TickerDecision.direction` is a `SignalType` enum. Accumulator keys in majority vote / weighted sums need consistent case. `SignalType.BUY.value == "buy"` (lowercase). `TickerConsensus.weighted_signal` and `majority_signal` store uppercase strings per D-05. Mixing cases silently creates extra dict keys.
**Why it happens:** `compute_bracket_summaries()` uses `decision.signal.value` (lowercase) as keys; `TickerConsensus` fields are uppercase strings per D-05 convention.
**How to avoid:** Use uppercase accumulator keys `{"BUY": 0, "SELL": 0, "HOLD": 0}` throughout `compute_ticker_consensus()`. Convert: `direction_key = ticker_dec.direction.value.upper()`.
**Warning signs:** `weighted_signal` or `majority_signal` returns unexpected values; all bars render gray (HOLD default).

### Pitfall 4: influence_weights fallback uses wrong base weight
**What goes wrong:** `influence_weights` dict from `compute_influence_edges()` only contains agents who received citations. Agents with no citations are absent from the dict. Using `influence_weights.get(agent_id, 1.0)` gives a flat 1.0 fallback instead of persona-specific `influence_weight_base`.
**Why it happens:** D-09 explicitly requires fallback to `persona.influence_weight_base`, not a flat value.
**How to avoid:** Build a lookup `persona_base: dict[str, float] = {p.id: p.influence_weight_base for p in personas}` before the loop. Fallback: `influence_weights.get(agent_id, persona_base.get(agent_id, 1.0))`.
**Warning signs:** Weighted signal diverges unexpectedly from majority signal in tests.

### Pitfall 5: StateStore field missing from snapshot()
**What goes wrong:** Adding `_ticker_consensus` to `StateStore.__init__` and `set_ticker_consensus()` but forgetting to include `ticker_consensus=self._ticker_consensus` in `snapshot()`. TUI always sees empty tuple; panel never updates.
**Why it happens:** `snapshot()` at state.py:191 explicitly lists all fields — it is not auto-generated.
**How to avoid:** Update `snapshot()` return value simultaneously with adding the field.
**Warning signs:** Panel stays at "Awaiting..." even after Round 1 completes.

### Pitfall 6: Bracket breakdown for a ticker uses global decisions
**What goes wrong:** Passing the full `agent_decisions` list (all 100 agents) to `compute_bracket_summaries()` for each ticker's bracket breakdown, instead of the filtered subset (agents with a `TickerDecision` for that ticker). Result: bracket bars show global sentiment, not ticker-specific.
**Why it happens:** `compute_bracket_summaries()` is reused without pre-filtering.
**How to avoid:** Before calling `compute_bracket_summaries()`, build a filtered list: `ticker_decisions_subset = [(aid, dec) for aid, dec in agent_decisions if any(td.ticker == ticker for td in dec.ticker_decisions)]`.
**Warning signs:** Bracket bars for all tickers look identical.

---

## Code Examples

Verified patterns from existing codebase:

### TickerConsensusPanel skeleton
```python
# Source: BracketPanel pattern (tui.py:314-377)
class TickerConsensusPanel(Widget):
    DEFAULT_CSS = """
    TickerConsensusPanel {
        width: 44;
        height: 100%;
        background: $panel;
        border-left: solid $secondary;
        padding: 1 1 0 1;
        overflow-y: auto;
    }
    """
    FILL_CHAR = "\u2588"
    EMPTY_CHAR = "\u2591"
    BAR_WIDTH = 12
    BRACKET_LABEL_WIDTH = 14

    _SIGNAL_COLORS: dict[str, str] = {
        "buy": "#66BB6A",
        "sell": "#EF5350",
        "hold": "#78909C",
    }

    def __init__(self) -> None:
        super().__init__()
        self._consensus: tuple[TickerConsensus, ...] = ()

    def update_consensus(self, consensus: tuple[TickerConsensus, ...]) -> None:
        self._consensus = consensus
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Tickers\n", style="bold #4FC3F7")
        if not self._consensus:
            text.append("No tickers\nextracted\n", style="#78909C")
            return text
        for tc in self._consensus:
            # header line: AAPL  BUY  w=0.74  (68% majority)  R3
            signal_color = self._SIGNAL_COLORS.get(tc.weighted_signal.lower(), "#78909C")
            text.append(f"{tc.ticker:<6}  ", style="bold #E0E0E0")
            text.append(f"{tc.weighted_signal:<4}", style=f"bold {signal_color}")
            text.append(f"  w=", style="#78909C")
            text.append(f"{tc.weighted_score:.2f}", style="#E0E0E0")
            text.append(f"  ({tc.majority_pct:.0f}% majority)", style="#78909C")
            text.append(f"  R{tc.round_num}\n", style="#78909C")
            # bracket mini-bars
            for s in tc.bracket_breakdown:
                dominant, pct = _dominant_signal(s)  # reuse BracketPanel logic
                color = self._SIGNAL_COLORS.get(dominant, "#78909C")
                filled = round(pct / 100 * self.BAR_WIDTH)
                empty = self.BAR_WIDTH - filled
                text.append(f"{s.display_name:<{self.BRACKET_LABEL_WIDTH}}  ")
                text.append("[")
                text.append(self.FILL_CHAR * filled, style=color)
                text.append(self.EMPTY_CHAR * empty, style="#333333")
                text.append(f"] {pct:.0f}%\n", style="#E0E0E0")
            text.append("\n")  # blank separator between tickers
        return text
```

### TickerConsensus dataclass
```python
# Source: D-05, BracketSummary pattern (state.py:32)
@dataclass(frozen=True)
class TickerConsensus:
    ticker: str
    round_num: int
    weighted_signal: str      # "BUY" / "SELL" / "HOLD"
    weighted_score: float     # 0.0-1.0
    majority_signal: str      # "BUY" / "SELL" / "HOLD"
    majority_pct: float       # 0.0-100.0
    bracket_breakdown: tuple[BracketSummary, ...]
```

### compute_ticker_consensus() skeleton
```python
# Source: compute_bracket_summaries() pattern (simulation.py:87)
def compute_ticker_consensus(
    agent_decisions: list[tuple[str, AgentDecision]],
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
    influence_weights: dict[str, float],
    round_num: int,
) -> tuple[TickerConsensus, ...]:
    persona_base: dict[str, float] = {p.id: p.influence_weight_base for p in personas}
    # Collect all tickers present across decisions
    all_tickers: set[str] = set()
    for _, dec in agent_decisions:
        for td in dec.ticker_decisions:
            all_tickers.add(td.ticker)

    result: list[TickerConsensus] = []
    for ticker in sorted(all_tickers):
        majority_counts: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        weighted_sums: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        ticker_agent_subset: list[tuple[str, AgentDecision]] = []

        for agent_id, dec in agent_decisions:
            if dec.signal == SignalType.PARSE_ERROR:
                continue
            if not dec.ticker_decisions:
                continue
            td = next((t for t in dec.ticker_decisions if t.ticker == ticker), None)
            if td is None:
                continue
            ticker_agent_subset.append((agent_id, dec))
            direction = td.direction.value.upper()
            w = influence_weights.get(agent_id, persona_base.get(agent_id, 1.0))
            majority_counts[direction] = majority_counts.get(direction, 0) + 1
            weighted_sums[direction] = weighted_sums.get(direction, 0.0) + dec.confidence * w

        total_votes = sum(majority_counts.values())
        total_weighted = sum(weighted_sums.values())
        majority_signal = max(majority_counts, key=lambda k: majority_counts[k])
        weighted_signal = max(weighted_sums, key=lambda k: weighted_sums[k])
        majority_pct = majority_counts[majority_signal] / total_votes * 100.0 if total_votes > 0 else 0.0
        weighted_score = weighted_sums[weighted_signal] / total_weighted if total_weighted > 0.0 else 0.0

        bracket_breakdown = compute_bracket_summaries(ticker_agent_subset, personas, brackets)

        result.append(TickerConsensus(
            ticker=ticker,
            round_num=round_num,
            weighted_signal=weighted_signal,
            weighted_score=weighted_score,
            majority_signal=majority_signal,
            majority_pct=majority_pct,
            bracket_breakdown=bracket_breakdown,
        ))
    return tuple(result)
```

### _poll_snapshot() diff addition
```python
# Source: bracket panel diff pattern (tui.py:891-895)
if snapshot.ticker_consensus != self._prev_ticker_consensus:
    self._ticker_consensus_panel.update_consensus(snapshot.ticker_consensus)
    self._prev_ticker_consensus = snapshot.ticker_consensus
```

### simulation.py call sites
```python
# Source: set_bracket_summaries call pattern (simulation.py:976-977, 1108-1109, 1226-1227)
# Add after each existing set_bracket_summaries call (Rounds 1, 2, 3):
if state_store is not None:
    await state_store.set_ticker_consensus(
        compute_ticker_consensus(
            round_N_decisions, personas, brackets, round_N_weights, round_num=N
        )
    )
```

Note: For Round 3, `round3_weights` is not computed in the current codebase (only Round 1 and Round 2 weights are computed explicitly). The simulation uses `round2_weights` for Round 3 dispatch. Use `round2_weights` as the `influence_weights` argument when calling `compute_ticker_consensus()` for Round 3.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Textual `ScrollView` (now deprecated) | `overflow-y: auto` TCSS on Widget | Textual v0.40+ | Direct CSS property; no wrapper widget needed |
| `textual.containers.ScrollView` | `textual.containers.ScrollableContainer` | Textual v0.xx | ScrollableContainer is the modern wrapper if CSS approach is insufficient |

**Confirmed for Textual 8.1.1:** `overflow-y: auto` is a valid TCSS property (`RenderStyles.overflow_y` exists). `get_content_height()` measures Rich Text height automatically — no `get_content_height()` override needed.

---

## Open Questions

1. **Round 3 influence_weights availability**
   - What we know: `round2_weights` are computed at line 1100 and used for Round 3 dispatch. After Round 3 completes, no `round3_weights` are computed (line 1222 shows Round 3 bracket summaries computed without a new `compute_influence_edges()` call).
   - What's unclear: Whether to (a) use `round2_weights` for Round 3 ticker consensus, or (b) compute new `round3_weights` after Round 3 (adds a Neo4j call).
   - Recommendation: Use `round2_weights` for Round 3. This matches the existing `set_bracket_summaries()` call pattern which also doesn't compute new weights for Round 3. Avoids adding an unplanned Neo4j query.

2. **Awaiting state display during active rounds**
   - What we know: D-03 says panel shows "Awaiting R{n}..." per round. D-13 covers the no-ticker case.
   - What's unclear: When ticker consensus is not yet pushed (e.g., mid-Round-1), `snapshot.ticker_consensus` is empty tuple `()`. The panel currently shows "No tickers\nextracted" for empty tuple — but that is inaccurate during live simulation.
   - Recommendation: Distinguish "empty because no tickers extracted" from "empty because round not done yet" using `snapshot.phase`. If `phase != IDLE` and `ticker_consensus == ()`, render "Awaiting R{round_num}..." instead. This requires reading `snapshot.phase` in `render()`, which means passing phase into the widget via `update_consensus(consensus, phase, round_num)`.

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — pure Python code changes to existing modules, no new CLI tools, services, or runtimes required).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0 |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/test_state.py tests/test_tui.py tests/test_simulation.py -x -q` |
| Full suite command | `uv run pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DTUI-01 | `TickerConsensus` dataclass is frozen and has correct defaults | unit | `uv run pytest tests/test_state.py::test_ticker_consensus_frozen -x` | Wave 0 |
| DTUI-01 | `StateStore.set_ticker_consensus()` stores and exposes via snapshot | unit | `uv run pytest tests/test_state.py::test_set_ticker_consensus -x` | Wave 0 |
| DTUI-01 | `TickerConsensusPanel.render()` produces correct header line format | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_header -x` | Wave 0 |
| DTUI-01 | Panel shows "Awaiting..." when consensus is empty | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_empty_state -x` | Wave 0 |
| DTUI-02 | `compute_ticker_consensus()` computes correct majority signal and pct | unit | `uv run pytest tests/test_simulation.py::test_compute_ticker_consensus_majority -x` | Wave 0 |
| DTUI-02 | `compute_ticker_consensus()` computes correct weighted signal and score | unit | `uv run pytest tests/test_simulation.py::test_compute_ticker_consensus_weighted -x` | Wave 0 |
| DTUI-02 | Both values visible in rendered output | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_both_signals -x` | Wave 0 |
| DTUI-03 | Bracket breakdown is ticker-scoped (not global) | unit | `uv run pytest tests/test_simulation.py::test_compute_ticker_consensus_bracket_scope -x` | Wave 0 |
| DTUI-03 | `TickerConsensusPanel.render()` produces 10 bracket rows per ticker | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_bracket_bars -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_state.py tests/test_tui.py tests/test_simulation.py -x -q`
- **Per wave merge:** `uv run pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

All Phase 19 test functions listed above are new — they do not exist yet. All must be created before or during Wave 1 implementation:

- [ ] `tests/test_state.py` — add `test_ticker_consensus_frozen`, `test_set_ticker_consensus`
- [ ] `tests/test_tui.py` — add `test_ticker_consensus_panel_render_header`, `test_ticker_consensus_panel_empty_state`, `test_ticker_consensus_panel_render_both_signals`, `test_ticker_consensus_panel_render_bracket_bars`
- [ ] `tests/test_simulation.py` — add `test_compute_ticker_consensus_majority`, `test_compute_ticker_consensus_weighted`, `test_compute_ticker_consensus_bracket_scope`

Existing files `tests/test_state.py`, `tests/test_tui.py`, `tests/test_simulation.py` all exist and have established fixture patterns to extend.

---

## Sources

### Primary (HIGH confidence)

- Live codebase inspection — `src/alphaswarm/tui.py` BracketPanel (lines 314-377), compose() (lines 698-719), _poll_snapshot() (lines 851-897)
- Live codebase inspection — `src/alphaswarm/state.py` BracketSummary (line 32), StateSnapshot (line 73), StateStore (line 87), set_bracket_summaries() (line 177), snapshot() (line 191)
- Live codebase inspection — `src/alphaswarm/simulation.py` compute_bracket_summaries() (lines 87-140), run_simulation() (lines 841-1250), all 3 set_bracket_summaries() call sites
- Live codebase inspection — `src/alphaswarm/types.py` TickerDecision (line 169), AgentDecision (line 178-187), SignalType
- Live runtime verification — `textual 8.1.1` (confirmed via `uv run python -c "import textual; print(textual.__version__)"`): `RenderStyles.overflow_y` exists, `Widget.get_content_height()` measures Rich Text height automatically
- `19-CONTEXT.md` — all locked decisions D-01 through D-14
- `19-UI-SPEC.md` — display format spec, component inventory, constants, typography

### Secondary (MEDIUM confidence)

- `pyproject.toml` — confirmed textual>=8.1.1, pytest>=8.0, pytest-asyncio>=0.24.0, asyncio_mode="auto"
- `.planning/config.json` — confirmed nyquist_validation=true, commit_docs=true

### Tertiary (LOW confidence)

None — all claims verified against live codebase or runtime inspection.

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all packages already installed, versions verified at runtime
- Architecture: HIGH — all patterns verified from live codebase; `BracketPanel` is the exact template
- Pitfalls: HIGH — identified from code path analysis of actual simulation.py and state.py behavior
- Textual scroll: HIGH — verified `RenderStyles.overflow_y` and `get_content_height()` behavior at runtime

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable libraries, not fast-moving)
