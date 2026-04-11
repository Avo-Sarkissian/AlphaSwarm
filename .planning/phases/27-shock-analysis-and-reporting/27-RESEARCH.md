# Phase 27: Shock Analysis and Reporting - Research

**Researched:** 2026-04-11
**Domain:** Neo4j Cypher query authoring, Jinja2 template extension, Textual TUI widget state transitions, ReACT report pipeline integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**TUI Exposure**
- D-01: BracketPanel gains a "delta mode" that activates post-simulation when a shock was detected for the current cycle. The panel switches from live signal-proportion bars to before/after diff bars showing how each bracket's BUY/SELL/HOLD split changed across the shock boundary.
- D-02: Delta mode activates via the existing `_poll_snapshot()` 200ms tick — the same mechanism used for all other StateStore→TUI reactivity. When `SimulationPhase.COMPLETE` is reached AND a ShockEvent exists for the cycle, BracketPanel renders delta bars instead of live bars.
- D-03: The TUI delta view is a compact summary only. Full agent-level detail (pivots, held-firm, bracket aggregations) lives in the report section.

**Neo4j Query Strategy**
- D-04: No new Neo4j schema changes. Use `ShockEvent.injected_before_round` to determine the shock boundary. For a shock at `injected_before_round=N`, query Decision nodes where `round == N-1` (pre) and `round == N` (post).
- D-05: `(ShockEvent)-[:PRECEDES]->(Decision)` edges remain deferred — not added in Phase 27.
- D-06: Two new `GraphStateManager` methods: `read_shock_event(cycle_id)` (returns ShockEvent metadata or None if no shock), and `read_shock_impact(cycle_id)` (returns per-agent pre/post signals, bracket aggregations, pivot list).

**Pivot / Held-Firm Metric**
- D-07: An agent **pivoted** if its signal changed between the round immediately before the shock and the round after: `pre_signal != post_signal`.
- D-08: An agent **held firm** if `pre_signal == post_signal` regardless of confidence delta.
- D-09: Baseline is always "round immediately before shock" — `injected_before_round=2` means compare Round 1 (pre) vs Round 2 (post); `injected_before_round=3` means Round 2 (pre) vs Round 3 (post).
- D-10: Do not use `flip_type` on RationaleEpisode for pivot detection. Compute directly from Decision nodes by round comparison.

**Report Section (Section 11)**
- D-11: New tool key `shock_impact` maps to template `11_shock_impact.j2`. Added to `TOOL_TO_TEMPLATE` and appended to end of `SECTION_ORDER` (after `portfolio_impact`).
- D-12: Section renders **only when a ShockEvent exists** for the cycle. When `read_shock_event()` returns None, the section is skipped entirely — no placeholder text.
- D-13: Section content:
  1. Shock header: shock text, injected before round N, timestamp
  2. Bracket-level signal shift table: per-bracket BUY/SELL/HOLD % before vs after, delta column
  3. Pivot count summary: total pivoted, total held firm, pivot rate %
  4. Agent pivot list: agents who changed signal (bracket, agent_id, pre_signal→post_signal)
  5. Held-firm notable agents: agents in minority-signal brackets who held firm (dissenter-style)

### Claude's Discretion
- Exact BracketPanel delta bar rendering style (arrow indicators, color delta, or side-by-side bars)
- Whether `read_shock_impact()` is a single compound query or split into sub-queries
- Held-firm threshold for "notable held-firm" agents (e.g., only surface held-firm agents whose bracket majority shifted)
- Whether the TUI BracketPanel delta mode persists until user quits, or reverts after N seconds

### Deferred Ideas (OUT OF SCOPE)
- `(ShockEvent)-[:PRECEDES]->(Decision)` relationship
- Multi-shock per cycle analysis
- Confidence delta as a secondary pivot signal
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SHOCK-04 | User can see a before/after consensus comparison in the TUI or report showing how signals, confidence, and bracket distributions shifted after the shock | Covered by BracketPanel delta mode (D-01/D-02) + Section 11 bracket-level table (D-13 item 2) |
| SHOCK-05 | Post-simulation report includes a dedicated shock impact section showing which agents pivoted, which held firm, and bracket-level shift aggregations | Covered by Section 11 template + `read_shock_impact()` (D-06, D-11, D-13) |
</phase_requirements>

---

## Summary

Phase 27 adds a shock impact analysis layer on top of the Phase 26 ShockEvent infrastructure. It has two delivery surfaces: a BracketPanel "delta mode" in the TUI that activates post-simulation (SHOCK-04), and a new Section 11 in the post-simulation report (SHOCK-05).

All three source files have well-established patterns to follow. `graph.py` already contains nine read methods that use the `session-per-method` + `execute_read` + static `_tx` function pattern — adding `read_shock_event` and `read_shock_impact` follows that exact pattern with no new complexity. `report.py` already handles conditional sections via `TOOL_TO_TEMPLATE` + `SECTION_ORDER` with `shock_impact` pre-seeded as a `ToolObservation` before the ReACT engine runs, exactly mirroring how `portfolio_impact` was wired in Phase 25. `tui.py` already has an `_delta_mode` flag pattern in how `_check_shock_window` controls overlay push — adding `_delta_mode: bool` to `BracketPanel` and triggering it from `_poll_snapshot` follows the same rising-edge latch pattern.

The critical technical insight is that `shock_impact` differs from `portfolio_impact` in one key way: it is unconditionally computed at report-time by querying Neo4j (no user-provided external file), but is still skipped when no ShockEvent exists for the cycle. The `read_shock_event()` guard controls this: if it returns `None`, the CLI handler does not create a `shock_impact` ToolObservation and the section is silently absent from both markdown and HTML output.

**Primary recommendation:** Pre-seed `shock_impact` as a `ToolObservation` in the CLI `report` handler (same as `portfolio_impact`) so it bypasses the probabilistic ReACT loop, and gate pre-seeding on `read_shock_event()` returning non-None.

---

## Standard Stack

### Core (all already installed — no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| neo4j (async driver) | >=5.x (project) | `read_shock_event` + `read_shock_impact` Cypher queries | Existing graph layer, all read methods use this driver |
| Jinja2 | >=3.x (project) | `11_shock_impact.j2` template rendering | Existing report templating engine |
| textual | >=8.1.1 | BracketPanel delta mode UI | Existing TUI framework |
| structlog | project | `component="report"` / `component="graph"` loggers | Established logging convention |
| pydantic | project | Typed dataclass for shock impact result if needed | Config/validation layer |

**Installation:** No new packages required. All dependencies are already present in the project.

---

## Architecture Patterns

### Pattern 1: Pre-seeded ToolObservation (portfolio_impact precedent)

**What:** Before the ReACT loop runs, the CLI handler unconditionally computes the shock impact data, wraps it in a `ToolObservation`, and passes it in `pre_seeded_observations` to `ReportEngine`. The ReACT loop never needs to call `shock_impact` — the data is already in context. An idempotent tool closure is also registered in `tools` so the LLM can reference it.

**When to use:** Any report section where the data must be deterministically present (not LLM-probabilistic) and requires a pre-computation step before the ReACT loop.

**Exact CLI wiring pattern** (from `cli.py` around line 740, portfolio precedent):
```python
# In report_handler, after building `tools` dict:
pre_seeded_observations: list[ToolObservation] = []

# --- Shock impact wiring (analogous to portfolio wiring at line 740) ---
shock_event = await gm.read_shock_event(cycle_id)
if shock_event is not None:
    shock_impact_result = await gm.read_shock_impact(cycle_id)
    shock_obs = ToolObservation(
        tool_name="shock_impact",
        tool_input={"cycle_id": cycle_id},
        result=shock_impact_result,
    )
    pre_seeded_observations.append(shock_obs)

    async def _shock_impact_tool(**kw: object) -> dict:
        return shock_impact_result

    tools["shock_impact"] = _shock_impact_tool
```

Note: `shock_impact` does NOT need a `build_react_system_prompt` extension — the ReACT LLM does not need to call it. Pre-seeding is the entire integration path.

### Pattern 2: GraphStateManager read method (session-per-method)

**What:** Every read in `graph.py` opens a fresh `async with self._driver.session(database=self._database) as session:` and calls `session.execute_read(self._static_tx_fn, args)`. The `_tx` function is a `@staticmethod async def` that runs the Cypher and returns a typed result.

**`read_shock_event` Cypher** (single node read):
```cypher
MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
RETURN se.shock_id AS shock_id,
       se.shock_text AS shock_text,
       se.injected_before_round AS injected_before_round,
       se.created_at AS created_at
LIMIT 1
```
Returns a single dict or `None` (use `result.single()` pattern, same as `read_consensus_summary`).

**`read_shock_impact` Cypher design** (compound — pre/post agent decisions):

The query needs to:
1. Look up the ShockEvent for the cycle to get `injected_before_round`
2. Query Decision nodes at `round = injected_before_round - 1` (pre) and `round = injected_before_round` (post) for all agents
3. JOIN pre/post on `agent_id` to compute pivot flag and bracket deltas

Two sub-query approach is recommended (per Claude's Discretion) to keep Cypher readable. First sub-query collects pre/post rows per agent; second computes bracket aggregations. Both can be in one `session.execute_read` call via two `await tx.run(...)` calls in the same `_tx` function, or the method can issue two separate `session.execute_read` calls.

Single-query approach using `WITH` chaining also works:
```cypher
MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
WITH se.injected_before_round AS shock_round
MATCH (a:Agent)-[:MADE]->(pre:Decision {cycle_id: $cycle_id, round: shock_round - 1})
MATCH (a)-[:MADE]->(post:Decision {cycle_id: $cycle_id, round: shock_round})
RETURN a.id AS agent_id,
       a.name AS agent_name,
       a.bracket AS bracket,
       pre.signal AS pre_signal,
       post.signal AS post_signal,
       pre.confidence AS pre_confidence,
       post.confidence AS post_confidence,
       (pre.signal <> post.signal) AS pivoted
ORDER BY a.bracket, a.id
```
Then Python aggregates bracket distributions and pivot counts from this result set.

**Why Python aggregation over Cypher aggregation:** The bracket shift table, pivot list, and held-firm notable agents all require the same raw per-agent rows. Computing in Python from one result set avoids 3 round-trips to Neo4j.

### Pattern 3: BracketPanel delta mode (flag + render branch)

**What:** `BracketPanel` gains `_delta_mode: bool = False` and `_delta_data: dict | None = None` instance attributes. In `render()`, when `_delta_mode is True`, it renders delta bars instead of live bars. Activation is via `_poll_snapshot()` rising-edge detection.

**Activation condition** in `_poll_snapshot()`:
```python
# After the existing SimulationPhase.COMPLETE check block:
if (
    snapshot.phase == SimulationPhase.COMPLETE
    and self._cycle_id is not None
    and not self._bracket_panel_delta_active
):
    # Check for shock asynchronously — use run_worker
    self.run_worker(
        self._activate_bracket_delta_mode(self._cycle_id),
        exclusive=False,
        exit_on_error=False,
    )
    self._bracket_panel_delta_active = True  # latch — only trigger once
```

`_activate_bracket_delta_mode` is an async worker that calls `gm.read_shock_impact(cycle_id)`, and if data exists, calls `bracket_panel.enable_delta_mode(delta_data)`.

**Important:** `_poll_snapshot` is a sync method. The `gm` (GraphStateManager) call must go through `run_worker` — the same pattern used in `_on_shock_submitted`. The latch flag `_bracket_panel_delta_active: bool = False` prevents re-triggering on every 200ms tick.

**Delta bar rendering style** (Claude's Discretion — recommended): Side-by-side `pre → post` percentages with a delta indicator. Keeps the same bar widget positions.
```
Quants        [████████░░░░░░░░░░░░] 40% BUY  →  [██████████████░░░░░░] 70% BUY  (+30%)
```
Alternatively, a simpler delta-only bar:
```
Quants  BUY  +30%  [██████░░░░░░░░░░░░░░]   (color: green for positive, red for negative)
```
The simpler delta-only bar fits better in the 40-char panel width (BAR_WIDTH=20, panel width=40). Recommended.

**Delta mode persistence:** Persists until user quits (no auto-revert). Once the simulation is COMPLETE and shock data is loaded, the panel stays in delta mode. This is consistent with how the TUI generally freezes state at COMPLETE.

### Pattern 4: Conditional section in TOOL_TO_TEMPLATE / SECTION_ORDER

**What:** `TOOL_TO_TEMPLATE` and `SECTION_ORDER` in `report.py` are static lists. `shock_impact` is added as an entry in both. The conditional behavior (skip when no shock) is NOT enforced by these lists — it is enforced upstream by whether a `shock_impact` ToolObservation was ever created. If the observation was never created (no shock in cycle), `obs_by_tool.get("shock_impact")` returns `None` and `ReportAssembler.assemble()` silently skips the section (existing behavior at line 398-407).

```python
# In report.py:
TOOL_TO_TEMPLATE: dict[str, str] = {
    # ... existing entries ...
    "portfolio_impact": "10_portfolio_impact.j2",
    "shock_impact": "11_shock_impact.j2",      # ADD
}

SECTION_ORDER: list[str] = [
    # ... existing entries ...
    "portfolio_impact",
    "shock_impact",                              # ADD (last)
]
```

### Pattern 5: HTML template extension for shock_impact

The `report.html.j2` template renders sections using `sections.get("shock_impact")` conditional blocks, identical to the `portfolio_impact` blocks starting at line 293. The template uses `sections` dict that is built from `{obs.tool_name: obs.result for obs in observations}` in `assemble_html()`. No changes to `assemble_html()` are needed — the section data will be available in `sections["shock_impact"]` when a shock occurred.

### Anti-Patterns to Avoid

- **Using flip_type from RationaleEpisode for pivot detection:** `flip_type` tracks inter-round flips independent of shock timing. D-10 explicitly forbids this. Always compare Decision nodes by round number.
- **Putting shock_impact in the ReACT system prompt as a callable tool:** The LLM does not need to call it. Pre-seeding bypasses the probabilistic dispatch. Adding it to the prompt risks the LLM trying to call it before it is in the tools dict.
- **Making `read_shock_impact` return None when no shock:** `read_shock_impact` should only be called after `read_shock_event` confirms a ShockEvent exists. If called on a no-shock cycle it will return empty data (no pre-round exists for `injected_before_round - 1`). Guard in the CLI handler, not in the graph method.
- **Calling `gm.read_shock_impact()` synchronously from `_poll_snapshot()`:** `_poll_snapshot` is a sync Textual timer callback. All async graph calls must go through `run_worker`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pre/post bracket aggregation | Custom Python aggregation class | Python `collections.defaultdict` over Cypher result rows | One result set, aggregate in-memory; no graph round-trip |
| Bracket majority detection | New majority-signal algorithm | Copy `_read_key_dissenters_tx` bracket-majority CASE logic | Already validated in graph.py line 1308-1316 |
| Delta bar rendering | New Rich widget subclass | Add `_delta_mode` branch inside existing `BracketPanel.render()` | Same widget, same position, different data |
| Shock section conditioning | New `ReportAssembler` subclass | Absence of ToolObservation = section skip (existing behavior) | `obs_by_tool.get()` already handles missing keys silently |

---

## Common Pitfalls

### Pitfall 1: `injected_before_round - 1` produces round 0 for `injected_before_round=1`
**What goes wrong:** If a ShockEvent had `injected_before_round=1`, querying `round = 0` would return no Decision nodes (rounds start at 1).
**Why it happens:** The Phase 26 shock queue only allows shock before Round 2 or Round 3 (`injected_before_round` is 2 or 3). But the code should guard explicitly.
**How to avoid:** In `read_shock_impact`, assert or guard that `injected_before_round >= 2` before constructing the Cypher. Log a warning and return empty result if `injected_before_round < 2`.
**Warning signs:** Empty pivot list for a cycle that definitely had a shock.

### Pitfall 2: `_poll_snapshot` re-triggers `_activate_bracket_delta_mode` on every tick
**What goes wrong:** Every 200ms tick after COMPLETE, the worker fires again — multiple parallel graph reads, possible flicker.
**Why it happens:** Without a latch flag, the COMPLETE condition is persistently true.
**How to avoid:** Use `_bracket_panel_delta_active: bool = False` latch on the dashboard widget, set to True on first trigger. Mirrors the `_shock_window_was_open` latch from Phase 26 (tui.py line 1018).

### Pitfall 3: `assemble_html()` does not receive shock_impact data
**What goes wrong:** HTML report does not show the shock section even when a shock occurred.
**Why it happens:** `assemble_html()` builds `sections = {obs.tool_name: obs.result for obs in observations}` from all observations. If `shock_impact` is in `pre_seeded_observations` and flows through `ReportEngine.run()`, it will be in the returned observations list — no special handling needed.
**How to avoid:** Verify the pre-seeded ToolObservation for `shock_impact` uses `tool_name="shock_impact"` (exact key match for template lookup).

### Pitfall 4: Held-firm "notable" threshold undefined
**What goes wrong:** Either no agents are surfaced (threshold too strict) or too many agents are listed (threshold too loose).
**Why it happens:** "Notable held-firm" is defined in D-13 as "agents in minority-signal brackets who held firm (dissenter-style)."
**How to avoid:** In Python post-processing of Cypher results: a held-firm agent is "notable" when their `pre_signal == post_signal` AND their bracket's majority signal SHIFTED (pre-shock bracket majority != post-shock bracket majority). This surfaces held-firm agents precisely in brackets where the shock caused the majority to change.

### Pitfall 5: Delta mode reads from `app_state.graph_manager` but the attribute may not exist on AppState
**What goes wrong:** `app_state.graph_manager` AttributeError in the delta worker.
**Why it happens:** `_activate_bracket_delta_mode` runs post-simulation and needs the graph manager. The worker runs async and attribute access must be guarded.
**How to avoid:** Check that `app_state.graph_manager is not None` before calling — same pattern as `_run_simulation` which checks `app.model_manager`, `app.graph_manager` before use.

---

## Code Examples

Verified patterns from existing source files:

### read_shock_event — session-per-method with single() record
```python
# Source: graph.py read_consensus_summary (line 1160) — same pattern
async def read_shock_event(self, cycle_id: str) -> dict | None:
    try:
        async with self._driver.session(database=self._database) as session:
            result = await session.execute_read(
                self._read_shock_event_tx, cycle_id
            )
    except Neo4jError as exc:
        raise Neo4jConnectionError(...) from exc
    return result

@staticmethod
async def _read_shock_event_tx(
    tx: AsyncManagedTransaction, cycle_id: str
) -> dict | None:
    result = await tx.run(
        """
        MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
        RETURN se.shock_id AS shock_id,
               se.shock_text AS shock_text,
               se.injected_before_round AS injected_before_round,
               se.created_at AS created_at
        LIMIT 1
        """,
        cycle_id=cycle_id,
    )
    record = await result.single()
    return dict(record) if record else None
```

### read_shock_impact — per-agent pre/post with Python aggregation
```python
# Source: graph.py read_key_dissenters (line 1279) — bracket majority pattern
# The TX function returns raw per-agent rows; Python aggregates brackets.
@staticmethod
async def _read_shock_impact_tx(
    tx: AsyncManagedTransaction, cycle_id: str
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
        WITH se.injected_before_round AS shock_round
        MATCH (a:Agent)-[:MADE]->(pre:Decision {cycle_id: $cycle_id, round: shock_round - 1})
        MATCH (a)-[:MADE]->(post:Decision {cycle_id: $cycle_id, round: shock_round})
        RETURN a.id AS agent_id,
               a.name AS agent_name,
               a.bracket AS bracket,
               pre.signal AS pre_signal,
               post.signal AS post_signal,
               (pre.signal <> post.signal) AS pivoted,
               shock_round AS shock_round
        ORDER BY a.bracket, a.id
        """,
        cycle_id=cycle_id,
    )
    return [dict(r) async for r in result]
```

### BracketPanel delta mode — flag + render branch (no new widget)
```python
# Source: BracketPanel.render() lines 351-377 — extend existing method
class BracketPanel(Widget):
    def __init__(self) -> None:
        super().__init__()
        self._summaries: tuple[BracketSummary, ...] = ()
        self._delta_mode: bool = False
        self._delta_data: dict | None = None   # result from read_shock_impact

    def enable_delta_mode(self, delta_data: dict) -> None:
        self._delta_mode = True
        self._delta_data = delta_data
        self.refresh()

    def render(self) -> Text:
        if self._delta_mode and self._delta_data:
            return self._render_delta()
        return self._render_live()
```

### Template section — conditional rendering (portfolio_impact precedent)
```jinja2
{# 11_shock_impact.j2 — mirrors 04_key_dissenters.j2 structure #}
## Shock Impact Analysis

**Shock:** {{ data.shock_text }}
**Injected before Round:** {{ data.injected_before_round }}

### Bracket Signal Shift

| Bracket | Pre-Shock BUY% | Post-Shock BUY% | Delta |
|---------|----------------|-----------------|-------|
{% for b in data.bracket_deltas %}
| {{ b.bracket }} | {{ "%.0f"|format(b.pre_buy_pct) }}% | {{ "%.0f"|format(b.post_buy_pct) }}% | {{ "%+.0f"|format(b.delta_buy_pct) }}% |
{% endfor %}

### Pivot Summary

- **Pivoted:** {{ data.pivot_count }} agents ({{ "%.1f"|format(data.pivot_rate_pct) }}%)
- **Held firm:** {{ data.held_firm_count }} agents
```

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest-asyncio (asyncio_mode = "auto") |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_graph.py tests/test_tui.py tests/test_report.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| SHOCK-04 | BracketPanel delta mode activates on COMPLETE + shock detected | unit | `pytest tests/test_tui.py -k "delta" -x -q` | Wave 0 |
| SHOCK-04 | `read_shock_event` returns ShockEvent dict when shock exists | unit | `pytest tests/test_graph.py -k "read_shock_event" -x -q` | Wave 0 |
| SHOCK-04 | `read_shock_impact` returns per-agent pre/post signals | unit | `pytest tests/test_graph.py -k "read_shock_impact" -x -q` | Wave 0 |
| SHOCK-05 | `shock_impact` ToolObservation pre-seeded when shock detected in CLI handler | unit | `pytest tests/test_cli.py -k "shock_impact" -x -q` | Wave 0 |
| SHOCK-05 | `11_shock_impact.j2` renders pivot table and bracket shift table | unit | `pytest tests/test_report.py -k "shock_impact" -x -q` | Wave 0 |
| SHOCK-05 | `TOOL_TO_TEMPLATE` and `SECTION_ORDER` include `shock_impact` | unit | `pytest tests/test_report.py -k "tool_to_template" -x -q` | Wave 0 |
| SHOCK-05 | Section skipped when `read_shock_event()` returns None | unit | `pytest tests/test_report.py -k "no_shock" -x -q` | Wave 0 |
| SHOCK-05 | HTML template renders shock section when data present | unit | `pytest tests/test_report.py -k "html_shock" -x -q` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_graph.py tests/test_tui.py tests/test_report.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

All test stubs listed below must be created as failing tests before implementation begins:

- [ ] `tests/test_graph.py` — `test_read_shock_event_returns_dict_when_exists` — SHOCK-04
- [ ] `tests/test_graph.py` — `test_read_shock_event_returns_none_when_no_shock` — SHOCK-04
- [ ] `tests/test_graph.py` — `test_read_shock_impact_returns_per_agent_rows` — SHOCK-04
- [ ] `tests/test_graph.py` — `test_read_shock_impact_pivot_flag_computed_correctly` — SHOCK-04
- [ ] `tests/test_tui.py` — `test_bracket_panel_enable_delta_mode_triggers_refresh` — SHOCK-04
- [ ] `tests/test_tui.py` — `test_bracket_panel_render_delta_uses_delta_data` — SHOCK-04
- [ ] `tests/test_tui.py` — `test_bracket_panel_live_mode_unchanged_without_shock` — SHOCK-04
- [ ] `tests/test_report.py` — `test_tool_to_template_contains_shock_impact` — SHOCK-05
- [ ] `tests/test_report.py` — `test_section_order_contains_shock_impact_after_portfolio` — SHOCK-05
- [ ] `tests/test_report.py` — `test_assemble_includes_shock_section_when_observation_present` — SHOCK-05
- [ ] `tests/test_report.py` — `test_assemble_skips_shock_section_when_no_observation` — SHOCK-05
- [ ] `tests/test_report.py` — `test_shock_impact_template_renders_bracket_delta_table` — SHOCK-05
- [ ] `tests/test_report.py` — `test_shock_impact_template_renders_pivot_list` — SHOCK-05
- [ ] `tests/test_cli.py` — `test_shock_impact_preseeded_when_shock_event_exists` — SHOCK-05

---

## Project Constraints (from CLAUDE.md)

| Directive | How it affects Phase 27 |
|-----------|------------------------|
| 100% async (`asyncio`) | `read_shock_event` and `read_shock_impact` must be `async def`; `_poll_snapshot` delta activation must use `run_worker` |
| Local First / No cloud APIs | No new external dependencies; all data from Neo4j graph |
| Max 2 models loaded simultaneously | Report handler already manages model lifecycle; shock_impact pre-seeding happens outside the Ollama call boundary |
| `structlog` logging | `read_shock_event` and `read_shock_impact` must use `self._log.debug(...)` with structured fields |
| Session-per-method Neo4j | Both new graph methods open their own `async with self._driver.session(...)` |
| `pytest-asyncio` (asyncio_mode="auto") | All async test functions are auto-discovered; no `@pytest.mark.asyncio` needed |
| Strict typing (`python 3.11+`) | Return types on new graph methods: `dict | None` and `dict`; new BracketPanel fields typed |
| No blocking I/O on event loop | `_poll_snapshot` must use `run_worker` for graph calls |

---

## Integration Points Summary

| File | Change | Decision |
|------|--------|----------|
| `src/alphaswarm/graph.py` | Add `read_shock_event(cycle_id)` and `read_shock_impact(cycle_id)` + static `_tx` functions | D-06 |
| `src/alphaswarm/report.py` | Add `"shock_impact": "11_shock_impact.j2"` to `TOOL_TO_TEMPLATE`; append `"shock_impact"` to `SECTION_ORDER` | D-11 |
| `src/alphaswarm/cli.py` | After `pre_seeded_observations = []`, add shock event detection and conditional pre-seeding | D-12 |
| `src/alphaswarm/tui.py` | Add `_delta_mode`, `_delta_data`, `enable_delta_mode()` to `BracketPanel`; add `_bracket_panel_delta_active` latch + worker call to dashboard's `_poll_snapshot` | D-01/D-02 |
| `src/alphaswarm/templates/report/11_shock_impact.j2` | New template file | D-13 |
| `src/alphaswarm/templates/report/report.html.j2` | Add `{% if sections.get("shock_impact") %}` section block | D-12 + Phase 24 D-05/D-08 |
| `.planning/REQUIREMENTS.md` | Add SHOCK-04 and SHOCK-05 entries to traceability table | Context.md requirement |

---

## Open Questions

1. **Delta bar data flow: where does `app_state.cycle_id` come from for the TUI delta worker?**
   - What we know: `_run_simulation` sets `self._cycle_id = result.cycle_id` after the simulation completes (tui.py line 834).
   - What's unclear: Whether `self._cycle_id` is accessible in `_poll_snapshot` (it's on the dashboard widget, not passed to BracketPanel).
   - Recommendation: Check that `self._cycle_id` is set before triggering `_activate_bracket_delta_mode(self._cycle_id)`. The cycle_id is available on the dashboard class — pass it as argument to the worker method.

2. **Does the `report.py` pre-seed approach need a `build_react_system_prompt` parameter for `include_shock`?**
   - What we know: `portfolio_impact` required `build_react_system_prompt(include_portfolio=True)` because the LLM needed a MUST-call mandate. Shock impact does NOT need this — it is purely pre-seeded, the LLM never calls it.
   - Recommendation: No change to `build_react_system_prompt`. The `shock_impact` observation is silently in context for LLM narrative generation but not explicitly mandated.

3. **`read_shock_impact` return shape for template consumption**
   - What we know: The Jinja2 template needs `data.bracket_deltas`, `data.pivot_count`, `data.held_firm_count`, `data.pivot_rate_pct`, `data.pivot_agents`, `data.notable_held_firm_agents`, `data.shock_text`, `data.injected_before_round`.
   - Recommendation: `read_shock_impact` returns a single dict with these keys, built from Python aggregation over the raw per-agent Cypher rows. The method calls `read_shock_event` internally to get `shock_text` and `injected_before_round`, or these are passed in from the CLI caller.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/alphaswarm/graph.py` — all nine existing read methods, `write_shock_event`, SCHEMA_STATEMENTS
- Direct code inspection: `src/alphaswarm/report.py` — TOOL_TO_TEMPLATE (line 312), SECTION_ORDER (line 325), `ReportEngine.run()`, `ReportAssembler.assemble()` and `assemble_html()`
- Direct code inspection: `src/alphaswarm/tui.py` — `BracketPanel` (line 314), `_poll_snapshot` (line 943), `_check_shock_window` (line 1010), `_shock_window_was_open` latch
- Direct code inspection: `src/alphaswarm/cli.py` — portfolio_impact pre-seeding block (lines 717-817)
- Direct code inspection: `src/alphaswarm/state.py` — `is_shock_window_open`, `shock_next_round`, `submit_shock`
- Direct code inspection: `src/alphaswarm/templates/report/10_portfolio_impact.j2` — conditional rendering reference
- Direct code inspection: `src/alphaswarm/templates/report/04_key_dissenters.j2` — section structure reference
- Direct code inspection: `src/alphaswarm/templates/report/report.html.j2` — HTML section pattern (lines 293-362)
- Direct code inspection: `.planning/phases/27-shock-analysis-and-reporting/27-CONTEXT.md` — all decisions D-01 through D-13

### Secondary (MEDIUM confidence)
- `.planning/phases/26-shock-injection-core/26-01-PLAN.md` — Wave 0 test stub patterns from Phase 26
- `.planning/REQUIREMENTS.md` — SHOCK-01/02/03 traceability confirms Phase 26 completion
- `tests/test_graph.py` — Phase 26 shock test patterns (lines 1427-1517)
- `tests/test_tui.py` — BracketPanel unit test structure (lines 246-304)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing dependencies, no new packages
- Architecture: HIGH — all patterns verified directly in source files
- Neo4j Cypher: HIGH — query shape derived from existing `_read_key_dissenters_tx` and Decision node structure confirmed in `write_decisions`
- TUI delta mode: HIGH — pattern directly mirrors `_shock_window_was_open` latch already in place
- CLI pre-seeding: HIGH — directly mirrors portfolio_impact wiring (lines 717-817 in cli.py)
- Template structure: HIGH — `10_portfolio_impact.j2` and `04_key_dissenters.j2` provide exact structural reference
- HTML extension: HIGH — `report.html.j2` pattern confirmed (sections.get() conditional blocks)
- Pitfalls: HIGH — all identified from existing code inspection

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (stable internal codebase; no external dependency churn expected)
