---
phase: 7
slug: rounds-2-3-peer-influence-and-consensus
status: draft
shadcn_initialized: false
preset: none
created: 2026-03-26
---

# Phase 7 -- UI Design Contract (CLI Terminal Output)

> Visual and interaction contract for Phase 7 terminal output. Phase 7 is a headless simulation phase with no graphical UI. The "UI" is structured CLI output via `print()` statements to stdout, extending the existing patterns from `cli.py`.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (Python CLI, not React/Next.js) |
| Preset | not applicable |
| Component library | none -- plain print() with ASCII formatting |
| Icon library | not applicable |
| Font | Terminal monospace (user's shell default) |

---

## Spacing Scale

Terminal output uses character-count spacing, not pixel spacing. All values are in character columns.

| Token | Value | Usage |
|-------|-------|-------|
| indent | 2 chars | All content lines inside a section block |
| col-gap | 1 char | Minimum gap between table columns |
| section-break | 1 blank line | Between sections within a report |
| report-break | 1 blank line | Between the `===` footer and next output |
| rule-width | 60 chars | `=` header/footer rules, matching existing pattern |
| dash-width | column-aligned | `-` separator under column headers, per-column width |

Exceptions: none

---

## Typography

Terminal output uses a single monospace font at a single size. "Typography" maps to formatting conventions.

| Role | Convention | Source |
|------|-----------|--------|
| Section header | `=` x 60 rule above and below | Existing: `_print_round1_report()` |
| Section title | 2-space indent, plain text, centered visually in `===` block | Existing: `"  Round 1 Complete"` |
| Table header | 2-space indent, left-aligned label columns, right-aligned numeric columns | Existing: bracket table in `_print_round1_report()` |
| Table separator | 2-space indent, `-` repeated per column width | Existing: `_print_round1_report()` |
| Table row | 2-space indent, same alignment as header | Existing pattern |
| Sub-header | 2-space indent, plain text with no rule | New: shift analysis sub-sections |
| Key-value pair | 2-space indent, `Label:` left-padded to 20 chars, value after | Existing: `_print_injection_summary()` |

---

## Color

No ANSI color codes in Phase 7. All output is plain text. Color is deferred to Phase 9-10 TUI (Textual CSS).

| Role | Value | Usage |
|------|-------|-------|
| Dominant (100%) | Terminal default foreground on default background | All output |
| Accent | none | Deferred to TUI |
| Destructive | none | No destructive CLI actions in this phase |

Rationale: Plain text ensures compatibility with all terminals, log piping, and CI output capture. The existing Phase 6 CLI uses no ANSI codes.

---

## Copywriting Contract

### Primary CTA

| Element | Copy |
|---------|------|
| CLI command | `python -m alphaswarm run "rumor text"` |
| CLI help text | `"Run full 3-round simulation"` (update from `"Run full Round 1 simulation"`) |

### Per-Round Report Headings

Each round prints a report block. The heading format is:

```
============================================================
  Round {N} Complete
============================================================
  Cycle ID: {cycle_id}
  Agents:   {success}/{total} ({errors} PARSE_ERROR)
```

Round numbers: `Round 1 Complete`, `Round 2 Complete`, `Round 3 Complete`.

Source: Existing `_print_round1_report()` pattern generalized.

### Bracket Table

Reuse existing column layout exactly:

```
  Bracket          BUY  SELL  HOLD   Avg Conf
  --------------- ----- ----- ----- ----------
  Quants              2     7     1       0.74
  Degens              6     1     3       0.81
  ...
```

Column widths: Bracket 15 left-aligned, BUY/SELL/HOLD 5 right-aligned each, Avg Conf 10 right-aligned with 2 decimal places.

Source: Existing `_print_round1_report()` lines 192-198 in cli.py.

### Shift Analysis Section (NEW)

Printed after Round 2 and Round 3 bracket tables:

```
  Signal Transitions (Round {N-1} -> Round {N})
  ----------------------------------------
  BUY -> SELL:  {n}      SELL -> BUY:  {n}
  BUY -> HOLD:  {n}      SELL -> HOLD: {n}
  HOLD -> BUY:  {n}      HOLD -> SELL: {n}
  Total agents shifted: {n}/100

  Confidence Drift by Bracket
  ----------------------------------------
  Quants          {+/-}{delta:.2f}
  Degens          {+/-}{delta:.2f}
  Sovereigns      {+/-}{delta:.2f}
  Macro           {+/-}{delta:.2f}
  Suits           {+/-}{delta:.2f}
  Insiders        {+/-}{delta:.2f}
  Agents          {+/-}{delta:.2f}
  Doom-Posters    {+/-}{delta:.2f}
  Policy Wonks    {+/-}{delta:.2f}
  Whales          {+/-}{delta:.2f}
```

Layout rules:
- Transition pairs arranged in two columns (6 possible transitions for 3 signals)
- Left column: transitions FROM a signal. Right column: matching reverse transition.
- Each transition formatted as `{FROM} -> {TO}: {count:>2}` with 6-char gap between columns.
- Bracket column: 15 chars left-aligned (same as bracket table). Delta: 6 chars right-aligned with sign prefix and 2 decimal places.
- `Total agents shifted` line at end of transitions block.

Source: CONTEXT.md D-11, D-12, D-15.

### Simulation Complete Summary (NEW)

Printed once after Round 3 report and shift analysis:

```
============================================================
  Simulation Complete
============================================================
  Cycle ID:       {cycle_id}
  Total Rounds:   3
  Signal Flips:   {r2_flips} (R1->R2) + {r3_flips} (R2->R3) = {total_flips} total
  Convergence:    {Yes/No} (flips {decreased/increased} between rounds)

  Final Consensus Distribution
  ----------------------------------------
  Bracket          BUY  SELL  HOLD   Avg Conf
  --------------- ----- ----- ----- ----------
  {same bracket table format as per-round, using Round 3 decisions}
============================================================
```

Key copy elements:
- **Convergence indicator**: `"Yes"` if Round 2->3 flips < Round 1->2 flips. `"No"` otherwise. Parenthetical shows `"flips decreased between rounds"` or `"flips increased between rounds"`.
- **Signal Flips line**: Shows per-transition totals and grand total.
- **Final Consensus Distribution**: Same bracket table format, using Round 3 (final locked) decisions.

Source: CONTEXT.md D-16.

### Notable Decisions

Printed after each round's bracket table (before shift analysis for Rounds 2-3):

```
  Notable Decisions (Top 5 by Confidence)
  -------------------------------------------------------
  {agent_id:<20} {signal:<5} {confidence:.2f}  {rationale_snippet}
```

Rationale snippets truncated at 80 characters via `_sanitize_rationale()`. Same format as existing Round 1 notable decisions.

Source: Existing `_print_round1_report()` lines 200-213 in cli.py.

### Empty State Copy

| State | Copy |
|-------|------|
| No decisions returned (all PARSE_ERROR) | `"  Warning: All {N} agents returned PARSE_ERROR. No valid decisions to report."` |
| No peer decisions found for an agent | Logged via structlog at warning level: `"no_peer_decisions_found"`. No user-facing print. Agent proceeds with empty peer context. |
| No signal flips between rounds | `"  No agents changed signal between rounds."` (replaces transition table) |

### Error State Copy

| Error | Copy |
|-------|------|
| Neo4j connection failure | `"Error: Cannot connect to Neo4j. Ensure Docker container is running."` (existing pattern) |
| Ollama connection failure | `"Error: Cannot connect to Ollama. Ensure Ollama is running."` (existing pattern) |
| Governor crisis (90% memory) | `"Error: Memory pressure critical (>{threshold}%). Simulation paused."` (logged by governor, not printed by CLI) |
| Simulation pipeline failure | `"Error: {exception_message}"` via existing `except Exception` handler in `_handle_run()` |

### Destructive Actions

None. Phase 7 has no destructive CLI actions. The `run` command is additive (creates new cycle, writes new decisions). No delete/reset operations.

---

## Peer Context String Format (Internal Data Contract)

This is not user-facing output but is the formatted string injected into agent prompts. Included here as a visual contract for the executor.

```
Peer Decisions (Round {N}):
1. [{bracket}] {SIGNAL} (conf: {X.XX}) "{rationale_snippet}"
2. [{bracket}] {SIGNAL} (conf: {X.XX}) "{rationale_snippet}"
3. [{bracket}] {SIGNAL} (conf: {X.XX}) "{rationale_snippet}"
4. [{bracket}] {SIGNAL} (conf: {X.XX}) "{rationale_snippet}"
5. [{bracket}] {SIGNAL} (conf: {X.XX}) "{rationale_snippet}"
```

Rules:
- Header line: `"Peer Decisions (Round {source_round}):"` per CONTEXT.md D-03
- Numbered 1-5, one peer per line
- Bracket in square brackets, lowercase (e.g., `[sovereigns]`)
- Signal UPPERCASE (e.g., `HOLD`, `BUY`, `SELL`)
- Confidence formatted as `X.XX` (2 decimal places)
- Rationale in double quotes, truncated at 80 chars via `_sanitize_rationale()`
- Total target: ~250 tokens for 5 peers

Source: CONTEXT.md D-01, D-02, D-03. RESEARCH.md Pattern 2.

---

## Progressive Output Timing

The simulation runs for approximately 10 minutes. Users must see progressive output to confirm the pipeline is alive.

| Event | Output |
|-------|--------|
| Simulation start | `"Starting 3-round simulation..."` (single line, no `===` block) |
| Round 1 complete | Full Round 1 report block (existing format) |
| Round 2 complete | Full Round 2 report block + shift analysis |
| Round 3 complete | Full Round 3 report block + shift analysis |
| Simulation complete | Simulation Complete summary block |

Each block prints immediately upon round completion. No buffering.

Source: CONTEXT.md D-14.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| not applicable | none | Python CLI -- no component registry |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
