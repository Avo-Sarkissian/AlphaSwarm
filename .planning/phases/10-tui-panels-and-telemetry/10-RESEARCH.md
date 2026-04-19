# Phase 10: TUI Panels and Telemetry - Research

**Researched:** 2026-03-27
**Domain:** Textual TUI widget composition, asyncio.Queue drain patterns, Ollama response metadata, psutil memory telemetry
**Confidence:** HIGH

## Summary

Phase 10 extends the Phase 9 Textual TUI with three new panels: a rationale sidebar (TUI-03), a telemetry footer (TUI-04), and a bracket aggregation panel (TUI-05). All new panels integrate into the existing 200ms `_poll_snapshot()` timer -- no independent timers needed. The foundational architecture is solid: `StateStore` already bridges simulation writes to TUI reads via immutable `StateSnapshot`, and `GovernorMetrics` already carries RAM, slot count, and active count.

The main technical challenges are: (1) RichLog has no native `prepend` method -- the sidebar must use `RichLog.write()` with `auto_scroll=True` (append to bottom, auto-scroll) rather than the CONTEXT.md-specified prepend-to-top, OR use a custom Widget with a render() method that reverses the entry list. Given the UI-SPEC's D-04 "newest entries prepend at top" requirement, a custom Widget with manual render is the cleanest approach. (2) TPS extraction from `ChatResponse` requires accessing `eval_count` and `eval_duration` fields from `BaseGenerateResponse` -- these are `Optional[int]` in ollama 0.6.1 and must be guarded against None. (3) The bracket panel requires a custom Widget with Rich markup rendering for progress bars -- Textual's built-in `ProgressBar` widget is step-based and not suitable for simple percentage displays.

**Primary recommendation:** Extend `StateStore` with three new data paths (rationale queue, TPS accumulator, bracket summaries), restructure the TUI layout from centered grid to main-row + bottom-row composition, and implement three new custom Widgets using Rich markup via `render()` methods driven by the existing `_poll_snapshot()` timer.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Right sidebar + bottom row layout. HeaderBar docked top, main row horizontal (agent-grid left + RationaleSidebar right), bottom row horizontal (TelemetryFooter narrow left + BracketPanel wide right)
- **D-02:** Rationale selection criterion -- high influence weight. Top INFLUENCED_BY edge weight holders each round. Entries pushed to asyncio.Queue on StateStore
- **D-03:** Entry format -- `> A_42 [BUY] momentum aligns with macro...` -- agent short ID, signal in brackets, rationale text truncated at ~50 characters. Signal word colored per theme
- **D-04:** Display style -- scrolling log, newest entries prepend at top. Older entries scroll down
- **D-05:** TPS tracked via Ollama eval_count + eval_duration. OllamaClient accumulates cumulative_tokens and cumulative_eval_ms. StateStore.update_tps() computes running TPS
- **D-06:** Telemetry footer format: `RAM: {pct}% | TPS: {tps} | Queue: {depth} | Slots: {slots}`. "Queue depth" = GovernorMetrics.active_count
- **D-07:** Bracket progress bar per bracket. Bar fill = dominant signal percentage. Bar color = dominant signal color (green BUY, red SELL, gray HOLD)
- **D-08:** All 10 brackets always shown. Update on round completion via RoundCompleteEvent carrying BracketSummary list

### Claude's Discretion
- Textual widget choices for progress bar (custom Widget subclass vs Static with rich markup bars)
- Exact CSS for new layout containers (widths/heights for sidebar and bottom row)
- How asyncio.Queue is exposed on StateStore -- whether rationale entries are pushed by simulation.py or by a dedicated high-influence selector post-round
- Whether TelemetryFooter uses set_interval independently or reads from the same 200ms snapshot tick

### Deferred Ideas (OUT OF SCOPE)
- Seed rumor text display in header -- not in Phase 10 requirements
- Agent hover tooltip (signal + confidence + rationale preview)
- Bracket row grouping in agent grid -- sequential layout from Phase 9 unchanged
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TUI-03 | Rationale sidebar streams most impactful agent reasoning outputs (asyncio.Queue, drains up to 5 per tick) | Custom Widget with reverse-ordered render(), asyncio.Queue(maxsize=50) on StateStore, drain at snapshot creation time |
| TUI-04 | Telemetry footer displays live RAM usage, tokens-per-second, API queue depth, active ResourceGovernor slots | Static widget with Rich markup, GovernorMetrics already carries RAM/slots/active_count, TPS via eval_count/eval_duration from ChatResponse |
| TUI-05 | Bracket aggregation panel shows per-bracket sentiment summary updated after each round | Custom Widget rendering 10 rows of Unicode block progress bars, BracketSummary already computed in simulation.py |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.1.1 | TUI framework -- Widget, Static, Container, RichLog, Theme | Already installed, Phase 9 baseline |
| psutil | 7.2.2 | RAM percentage via `virtual_memory().percent` | Already installed, Phase 3 dependency |
| ollama | 0.6.1 | ChatResponse.eval_count + eval_duration for TPS | Already installed, Phase 2 dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | (bundled with textual) | Rich markup rendering in Widget.render() for colored text | Signal tag coloring, bracket bar rendering |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom Widget for sidebar | RichLog with auto_scroll=True | RichLog appends at bottom only -- cannot prepend newest at top per D-04 without hacking internals. Custom Widget gives full control |
| Custom Widget for bracket bars | Textual ProgressBar | Built-in ProgressBar is step-based with optional gradient, not suitable for simple percentage fill with signal-colored bars |
| Static for telemetry | Custom Widget with render() | Static.update() is simpler for single-line content. Use Static -- it is designed for exactly this pattern |

**Installation:**
No new dependencies. All libraries already in pyproject.toml.

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    state.py          # MODIFY: Add RationaleEntry, asyncio.Queue, tps fields, bracket_summaries
    tui.py            # MODIFY: Restructure layout, add 3 new widgets, extend _poll_snapshot()
    ollama_client.py  # MODIFY: Extract eval_count/eval_duration, pass to state_store
    worker.py         # MODIFY: Pass state_store to infer(), extract TPS from ChatResponse
    simulation.py     # MODIFY: Push rationale entries and bracket summaries to StateStore
```

### Pattern 1: Snapshot-Driven Panel Updates (Extending Phase 9)
**What:** All new panels read from the same `StateSnapshot` in the existing `_poll_snapshot()` callback. No independent timers.
**When to use:** Always -- this is the established Phase 9 pattern.
**Example:**
```python
# In _poll_snapshot() -- extend existing method
def _poll_snapshot(self) -> None:
    snapshot = self.app_state.state_store.snapshot()

    # Existing: diff agent cells, update header
    # ...

    # NEW: Drain rationale entries from snapshot
    for entry in snapshot.rationale_entries:
        self._rationale_sidebar.add_entry(entry)

    # NEW: Update telemetry footer
    self._telemetry_footer.update_from_snapshot(snapshot)

    # NEW: Update bracket panel (only if summaries changed)
    if snapshot.bracket_summaries != self._prev_bracket_summaries:
        self._bracket_panel.update_summaries(snapshot.bracket_summaries)
        self._prev_bracket_summaries = snapshot.bracket_summaries

    self._prev_snapshot = snapshot
```

### Pattern 2: Queue Drain at Snapshot Creation Time
**What:** The `StateStore.snapshot()` method drains up to 5 entries from the asyncio.Queue using `get_nowait()` and includes them in the frozen `StateSnapshot.rationale_entries` tuple.
**When to use:** For rationale sidebar data flow.
**Why:** Draining in `snapshot()` ensures the TUI always gets fresh entries without the timer needing to interact with the Queue directly. The `StateSnapshot` remains the single data source for all panel updates.
**Example:**
```python
def snapshot(self) -> StateSnapshot:
    # Drain up to 5 rationale entries from queue
    entries: list[RationaleEntry] = []
    for _ in range(5):
        try:
            entries.append(self._rationale_queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    return StateSnapshot(
        # ... existing fields ...
        tps=self._compute_tps(),
        rationale_entries=tuple(entries),
        bracket_summaries=tuple(self._bracket_summaries),
    )
```

### Pattern 3: Custom Widget with Rich Markup render()
**What:** Bracket panel and rationale sidebar use custom Widget subclasses with `render()` returning Rich Text objects or markup strings. The `render()` method is called by Textual's compositor when the widget is refreshed.
**When to use:** When built-in widgets (Static, RichLog) don't provide the needed layout flexibility.
**Example:**
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

    def __init__(self) -> None:
        super().__init__()
        self._summaries: tuple[BracketSummary, ...] = ()

    def render(self) -> str:
        if not self._summaries:
            return self._render_idle()
        lines = []
        for s in self._summaries:
            bar = self._render_bar(s)
            lines.append(bar)
        return "\n".join(lines)

    def update_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        self._summaries = summaries
        self.refresh()
```

### Pattern 4: TPS Extraction from ChatResponse
**What:** After each non-streaming `chat()` call, extract `eval_count` and `eval_duration` (nanoseconds) from the `ChatResponse` and pass to `StateStore.update_tps()`.
**When to use:** In the worker inference path, after receiving the ChatResponse.
**Example:**
```python
# In worker.py AgentWorker.infer():
response = await self._client.chat(...)

# Extract TPS data from response metadata
if self._state_store is not None:
    eval_count = response.eval_count
    eval_duration = response.eval_duration
    if eval_count is not None and eval_duration is not None and eval_duration > 0:
        self._state_store.update_tps(eval_count, eval_duration)
```

### Anti-Patterns to Avoid
- **Independent timers per panel:** Do NOT create separate `set_interval` timers for telemetry, rationale, or bracket panels. All panels read from the SAME `_poll_snapshot()` callback at 200ms. Multiple timers create race conditions and unnecessary overhead.
- **Blocking Queue.get() in TUI callback:** The `_poll_snapshot()` method is synchronous. Use `get_nowait()` in a loop, NOT `await queue.get()`. Drain in `snapshot()` (which is also sync) or pre-drain in a sync-safe manner.
- **Direct RichLog.lines manipulation:** Do NOT hack `RichLog.lines.insert(0, ...)` to achieve prepend behavior. The internal cache and scroll state will break. Use a custom Widget instead.
- **Per-agent StateStore.update_tps() calls from TUI:** TPS updates flow from OllamaClient -> StateStore. The TUI only READS tps from the snapshot.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Progress bar rendering | Custom character-by-character bar builder | Rich markup with Unicode block chars + color tags | Rich handles color escaping and terminal compatibility |
| Memory monitoring | Direct psutil calls in TUI | GovernorMetrics.memory_percent from StateStore snapshot | Already computed by ResourceGovernor monitoring loop |
| Signal color lookup | Hardcoded hex values in each widget | ALPHASWARM_THEME variables ($success, $error, $secondary) | Theme-consistent, already defined and registered |
| Elapsed time formatting | strftime or manual formatting | Existing `_format_elapsed()` helper in tui.py | Already written and tested in Phase 9 |

**Key insight:** Most data the new panels need already exists somewhere in the system. The work is plumbing (connecting producers to StateStore, exposing via StateSnapshot) and rendering (3 new widgets reading from the same snapshot).

## Common Pitfalls

### Pitfall 1: RichLog Has No Prepend
**What goes wrong:** D-04 specifies "newest entries prepend at top." Developers will reach for RichLog.write() and try to make it prepend.
**Why it happens:** RichLog only supports `.write()` which appends. There is no `.prepend()`, `.insert()`, or reverse-scroll mode.
**How to avoid:** Use a custom Widget with a `render()` method that maintains an internal `deque` of entries and renders them newest-first. Or use RichLog with `auto_scroll=True` and accept newest-at-bottom (requires CONTEXT.md decision amendment). The UI-SPEC and CONTEXT.md both specify prepend-at-top, so custom Widget is the correct path.
**Warning signs:** Attempting to manipulate `RichLog.lines` directly, or finding that new entries appear at the bottom instead of the top.

### Pitfall 2: eval_count/eval_duration Are Optional[int]
**What goes wrong:** Accessing `response.eval_count` without None guards causes AttributeError or TypeError.
**Why it happens:** In ollama 0.6.1, `eval_count: Optional[int] = None` and `eval_duration: Optional[int] = None` are inherited from `BaseGenerateResponse`. They may be None for error responses or partial responses.
**How to avoid:** Always guard: `if eval_count is not None and eval_duration is not None and eval_duration > 0:`.
**Warning signs:** TypeError in TPS computation, division by zero.

### Pitfall 3: asyncio.Queue.get_nowait() in Synchronous Context
**What goes wrong:** `_poll_snapshot()` and `snapshot()` are synchronous methods. Using `await queue.get()` is not possible.
**Why it happens:** The 200ms timer callback in Textual is synchronous.
**How to avoid:** Use `queue.get_nowait()` in a try/except `asyncio.QueueEmpty` loop. This is non-blocking and safe in synchronous context. Drain in `StateStore.snapshot()` which is already sync.
**Warning signs:** `RuntimeError: cannot use 'await' in non-async context` or timer callback hanging.

### Pitfall 4: StateStore.snapshot() Growing with Queue Drain Side Effect
**What goes wrong:** `snapshot()` draining the queue means each call consumes entries. If snapshot is called more than once per tick (e.g., during testing or debugging), entries are lost.
**Why it happens:** `get_nowait()` removes items from the queue permanently.
**How to avoid:** Accept that snapshot() is the single consumer. Document that snapshot() has a side effect (queue drain). In tests, call snapshot() exactly once per "tick" to simulate real behavior. Alternatively, drain into a separate buffer field and have snapshot() read from the buffer.
**Warning signs:** Missing rationale entries in tests, entries appearing intermittently.

### Pitfall 5: eval_duration Is in Nanoseconds, Not Milliseconds
**What goes wrong:** TPS computed as `eval_count / eval_duration` gives extremely small numbers.
**Why it happens:** Ollama API returns `eval_duration` in nanoseconds. The CONTEXT.md D-05 says "cumulative_eval_ms" but the actual API field is nanoseconds.
**How to avoid:** Convert: `tps = cumulative_tokens / (cumulative_eval_ns / 1e9)`. Or track in nanoseconds consistently and convert to seconds for the final division.
**Warning signs:** TPS values like 0.000004 instead of 4.3.

### Pitfall 6: Layout Restructuring Breaks Phase 9 Grid Centering
**What goes wrong:** Phase 9 CSS uses `#grid-container { align: center middle; width: 100%; height: 100%; }`. Phase 10 replaces this with `#main-row` + `#bottom-row`. If the old CSS remains, layout conflicts occur.
**How to avoid:** Completely replace the Phase 9 CSS in `AlphaSwarmApp.CSS` with the new layout CSS from the UI-SPEC. Do not try to incrementally add containers around the existing centered layout.
**Warning signs:** Grid overlapping with sidebar, bottom row not visible, or layout rendering as a single column.

## Code Examples

### RationaleEntry Dataclass (New in state.py)
```python
# Source: 10-CONTEXT.md interaction contract
from dataclasses import dataclass
from alphaswarm.types import SignalType

@dataclass(frozen=True)
class RationaleEntry:
    agent_id: str        # e.g. "A_42"
    signal: SignalType    # BUY, SELL, HOLD
    rationale: str       # truncated at 50 chars by producer
    round_num: int       # which round this came from
```

### StateStore Expansion (state.py)
```python
# Source: 10-CONTEXT.md state mapping + UI-SPEC
import asyncio
from collections import deque

class StateStore:
    def __init__(self) -> None:
        # ... existing fields ...
        self._rationale_queue: asyncio.Queue[RationaleEntry] = asyncio.Queue(maxsize=50)
        self._cumulative_tokens: int = 0
        self._cumulative_eval_ns: int = 0
        self._bracket_summaries: tuple[BracketSummary, ...] = ()

    async def push_rationale(self, entry: RationaleEntry) -> None:
        """Push rationale entry. Drops oldest if full (non-blocking)."""
        try:
            self._rationale_queue.put_nowait(entry)
        except asyncio.QueueFull:
            # Drop oldest to make room
            try:
                self._rationale_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._rationale_queue.put_nowait(entry)

    def update_tps(self, eval_count: int, eval_duration_ns: int) -> None:
        """Accumulate TPS from Ollama response metadata. Thread-safe (GIL)."""
        self._cumulative_tokens += eval_count
        self._cumulative_eval_ns += eval_duration_ns

    async def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Store bracket summaries after each round."""
        async with self._lock:
            self._bracket_summaries = summaries

    def _compute_tps(self) -> float:
        """Compute running tokens-per-second."""
        if self._cumulative_eval_ns <= 0:
            return 0.0
        return self._cumulative_tokens / (self._cumulative_eval_ns / 1e9)

    def snapshot(self) -> StateSnapshot:
        # Drain up to 5 rationale entries
        entries: list[RationaleEntry] = []
        for _ in range(5):
            try:
                entries.append(self._rationale_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        return StateSnapshot(
            # ... existing fields ...
            tps=self._compute_tps(),
            rationale_entries=tuple(entries),
            bracket_summaries=self._bracket_summaries,
        )
```

### TPS Extraction in Worker (worker.py)
```python
# Source: ollama 0.6.1 BaseGenerateResponse fields (verified via source inspection)
# eval_count: Optional[int] = None  -- number of tokens evaluated in inference
# eval_duration: Optional[int] = None  -- duration in NANOSECONDS

async def infer(self, user_message: str, peer_context: str | None = None) -> AgentDecision:
    # ... existing message construction ...
    response = await self._client.chat(...)

    # Extract TPS data (Phase 10: TUI-04)
    if self._state_store is not None:
        eval_count = response.eval_count
        eval_duration = response.eval_duration
        if eval_count is not None and eval_duration is not None and eval_duration > 0:
            self._state_store.update_tps(eval_count, eval_duration)

    # ... existing parsing ...
```

### Custom Rationale Sidebar Widget (tui.py)
```python
# Source: Textual Widget.render() pattern + D-04 prepend requirement
from collections import deque
from rich.text import Text

class RationaleSidebar(Widget):
    DEFAULT_CSS = """
    RationaleSidebar {
        width: 40;
        height: 100%;
        background: $panel;
        border-left: solid $secondary;
        padding: 0 1;
    }
    """

    def __init__(self, max_entries: int = 50) -> None:
        super().__init__()
        self._entries: deque[RationaleEntry] = deque(maxlen=max_entries)

    def add_entry(self, entry: RationaleEntry) -> None:
        """Add entry to front (newest first per D-04)."""
        self._entries.appendleft(entry)
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Rationale\n", style="bold #4FC3F7")
        for entry in self._entries:
            text.append("> ", style="#78909C")
            text.append(f"{entry.agent_id} ", style="#E0E0E0")
            signal_color = {"buy": "#66BB6A", "sell": "#EF5350", "hold": "#78909C"}
            color = signal_color.get(entry.signal.value, "#78909C")
            text.append(f"[{entry.signal.value.upper()}] ", style=f"bold {color}")
            text.append(f"{entry.rationale}\n", style="#E0E0E0")
        return text
```

### TelemetryFooter Widget (tui.py)
```python
# Source: D-06 format + UI-SPEC telemetry warning colors
class TelemetryFooter(Static):
    DEFAULT_CSS = """
    TelemetryFooter {
        width: 1fr;
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._render_idle()

    def _render_idle(self) -> None:
        self.update(
            "  [#78909C]RAM:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]TPS:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Queue:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Slots:[/] [#78909C]--[/]"
        )

    def update_from_snapshot(self, snapshot: StateSnapshot) -> None:
        gm = snapshot.governor_metrics
        if gm is None:
            self._render_idle()
            return

        # RAM color based on threshold
        ram_pct = gm.memory_percent
        if ram_pct >= 90.0:
            ram_color = "#EF5350"
        elif ram_pct >= 80.0:
            ram_color = "#FFA726"
        else:
            ram_color = "#E0E0E0"

        self.update(
            f"  [#78909C]RAM:[/] [{ram_color}]{ram_pct:.0f}%[/]  "
            f"[#78909C]|[/]  [#78909C]TPS:[/] [#E0E0E0]{snapshot.tps:.1f}[/]  "
            f"[#78909C]|[/]  [#78909C]Queue:[/] [#E0E0E0]{gm.active_count}[/]  "
            f"[#78909C]|[/]  [#78909C]Slots:[/] [#E0E0E0]{gm.current_slots}[/]"
        )
```

### Bracket Panel Widget (tui.py)
```python
# Source: D-07 progress bar + UI-SPEC bracket bar colors
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
    FILL_CHAR = "\u2588"   # Full block
    EMPTY_CHAR = "\u2591"  # Light shade
    BAR_WIDTH = 20

    SIGNAL_COLORS = {
        "buy": "#66BB6A",   # $success
        "sell": "#EF5350",  # $error
        "hold": "#78909C",  # $secondary
    }

    def __init__(self) -> None:
        super().__init__()
        self._summaries: tuple[BracketSummary, ...] = ()

    def update_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        self._summaries = summaries
        self.refresh()

    def render(self) -> Text:
        text = Text()
        for s in self._summaries:
            dominant, pct = self._dominant_signal(s)
            color = self.SIGNAL_COLORS.get(dominant, "#78909C")
            filled = round(pct / 100 * self.BAR_WIDTH)
            empty = self.BAR_WIDTH - filled

            text.append(f"{s.display_name:<14}  ", style="#78909C")
            text.append("[")
            text.append(self.FILL_CHAR * filled, style=color)
            text.append(self.EMPTY_CHAR * empty, style="#333333")
            text.append(f"] {pct:.0f}%\n", style="#E0E0E0")
        return text

    @staticmethod
    def _dominant_signal(s: BracketSummary) -> tuple[str, float]:
        """Return (dominant_signal, percentage). Tie-break: BUY > SELL > HOLD."""
        counts = [("buy", s.buy_count), ("sell", s.sell_count), ("hold", s.hold_count)]
        dominant = max(counts, key=lambda x: x[1])
        total = s.total
        pct = (dominant[1] / total * 100) if total > 0 else 0.0
        return dominant[0], pct
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| RichLog for all scrolling content | Custom Widget with render() for reverse-ordered content | Textual 8.x | RichLog only appends; custom Widget needed for prepend behavior |
| Textual CSS inline strings | Textual CSS as class-level CSS attribute | Textual 1.0+ | CSS is defined as `DEFAULT_CSS` or class `CSS` string, not external files |
| Per-widget timers | Single snapshot-driven timer | Phase 9 decision | All panel updates from one 200ms _poll_snapshot() callback |

**Deprecated/outdated:**
- Textual `Log` widget: Replaced by `RichLog` which supports Rich renderables. Use `RichLog` or custom Widget, never `Log`.
- `$panel-darken-1` etc.: Older Textual theme variants. Use explicit hex values from ALPHASWARM_THEME.

## Open Questions

1. **Prepend vs. Append for Rationale Sidebar**
   - What we know: D-04 specifies "newest entries prepend at top." RichLog only appends. Custom Widget with render() can reverse-order entries.
   - What's unclear: Whether the user would accept "newest at bottom with auto-scroll" (simpler via RichLog) vs. strict "newest at top" (requires custom Widget).
   - Recommendation: Implement custom Widget per D-04 specification. The deque with `appendleft()` + `render()` approach is straightforward and matches the locked decision.

2. **TPS Extraction Point: Worker vs. OllamaClient**
   - What we know: D-05 says "OllamaClient accumulates" TPS data. But worker.py is where the ChatResponse is received and where state_store access makes sense.
   - What's unclear: Whether to inject state_store into OllamaClient (breaks its current clean API boundary) or have worker.py extract and forward to state_store.
   - Recommendation: Extract in worker.py and call `state_store.update_tps()`. This keeps OllamaClient unchanged (clean boundary) while still satisfying the TPS tracking requirement. The worker already has access to both the response and (will have access to) state_store.

3. **Queue Drain Side Effect in snapshot()**
   - What we know: snapshot() must be the single consumer. Each call drains up to 5 entries.
   - What's unclear: Whether to drain in snapshot() directly (side effect on a "read" method) or drain in a separate method called before snapshot().
   - Recommendation: Drain in snapshot(). The method already has side effects (computing elapsed_seconds from monotonic clock). Document the side effect clearly. Tests should be aware that each snapshot() call consumes queue entries.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_state.py tests/test_tui.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TUI-03 | Rationale sidebar drains up to 5 entries per snapshot | unit | `uv run pytest tests/test_state.py::test_rationale_queue_drain -x` | Wave 0 |
| TUI-03 | RationaleSidebar widget renders entries newest-first | unit | `uv run pytest tests/test_tui.py::test_rationale_sidebar_render -x` | Wave 0 |
| TUI-04 | TelemetryFooter displays RAM/TPS/Queue/Slots from snapshot | unit | `uv run pytest tests/test_tui.py::test_telemetry_footer_update -x` | Wave 0 |
| TUI-04 | update_tps accumulates eval_count/eval_duration correctly | unit | `uv run pytest tests/test_state.py::test_update_tps -x` | Wave 0 |
| TUI-04 | RAM warning colors at 80% and 90% thresholds | unit | `uv run pytest tests/test_tui.py::test_telemetry_ram_warning -x` | Wave 0 |
| TUI-05 | BracketPanel renders 10 bracket rows with progress bars | unit | `uv run pytest tests/test_tui.py::test_bracket_panel_render -x` | Wave 0 |
| TUI-05 | BracketPanel computes dominant signal and percentage | unit | `uv run pytest tests/test_tui.py::test_bracket_dominant_signal -x` | Wave 0 |
| ALL | TUI renders all 3 new panels without blocking | smoke | `uv run pytest tests/test_tui.py::test_full_dashboard_renders -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_state.py tests/test_tui.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_state.py` -- needs new tests for: rationale queue drain, update_tps, bracket_summaries, expanded StateSnapshot
- [ ] `tests/test_tui.py` -- needs new tests for: RationaleSidebar, TelemetryFooter, BracketPanel widgets, full dashboard layout with all panels

*(Existing test files cover Phase 9 functionality; Phase 10 tests must be added alongside implementation)*

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (asyncio). No blocking I/O on main event loop. The `_poll_snapshot()` callback is synchronous but must not block -- use `get_nowait()` not `await get()`.
- **Local First:** All inference local via Ollama. TPS is computed from local Ollama response metadata.
- **Memory Safety:** Monitor RAM via psutil. GovernorMetrics already carries memory_percent -- expose in telemetry footer.
- **Runtime:** Python 3.11+ strict typing. All new types must be properly annotated.
- **UI:** Textual >=8.1.1 for clean, minimalist terminal dashboard. Phase 10 extends the existing dashboard.
- **Testing:** pytest-asyncio. Textual headless `run_test()` for widget tests (pattern established in Phase 9).
- **Package manager:** uv. No new dependencies needed.
- **Developer preference:** Clean and minimalist aesthetic. Structured step-by-step implementation.

## Sources

### Primary (HIGH confidence)
- Textual 8.1.1 installed package -- verified via `uv pip show textual`
- ollama 0.6.1 installed package -- `BaseGenerateResponse` source inspected: `eval_count: Optional[int] = None`, `eval_duration: Optional[int] = None` (nanoseconds)
- psutil 7.2.2 -- verified working: `psutil.virtual_memory().percent`
- Existing codebase: `tui.py`, `state.py`, `ollama_client.py`, `worker.py`, `simulation.py`, `governor.py` -- all read and analyzed

### Secondary (MEDIUM confidence)
- [Textual RichLog docs](https://textual.textualize.io/widgets/rich_log/) -- write() API, no prepend method
- [Textual Widget docs](https://textual.textualize.io/guide/widgets/) -- render() pattern for custom widgets
- [Textual Static docs](https://textual.textualize.io/widgets/static/) -- update() method for single-line content
- [Ollama Chat API docs](https://docs.ollama.com/api/chat) -- eval_count/eval_duration field descriptions
- [Textual timer docs](https://textual.textualize.io/api/timer/) -- set_interval accepts seconds (0.2 for 200ms)

### Tertiary (LOW confidence)
- None. All findings verified against installed package source or official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages already installed and verified
- Architecture: HIGH -- extends well-established Phase 9 patterns; all integration points identified from source code
- Pitfalls: HIGH -- verified against actual API source (eval_count Optional[int], RichLog no prepend, queue.get_nowait() sync-safe)

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable -- no fast-moving dependencies)
