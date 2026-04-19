# Phase 9: TUI Core Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 09-tui-core-dashboard
**Areas discussed:** Integration model, Agent grid mapping, Cell visual density, Header bar scope

---

## Integration Model

| Option | Description | Selected |
|--------|-------------|----------|
| Same process, TUI-owned loop | TUI app launches first, simulation runs as Textual Worker in same event loop. StateStore as bridge. `tui "rumor"` single command. | ✓ |
| Separate processes via queue | Simulation as separate process, TUI connects via IPC/queue. More isolation, more complexity. | |
| TUI replaces `run` command | Existing `run` subcommand launches Textual instead of printing text. | |

**User's choice:** Same process, TUI-owned loop

---

**Follow-up: StateStore update granularity**

| Option | Description | Selected |
|--------|-------------|----------|
| Per-agent (live, as decided) | Simulation writes each agent's decision immediately after it resolves. Grid cells light up one-by-one. | ✓ |
| Per-round batch | Simulation writes all 100 decisions at round end via on_round_complete. Grid updates all at once. | |

**User's choice:** Per-agent (live, as decided)

---

## Agent Grid Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Sequential, row by row | Agents 1-10 in row 1, 11-20 in row 2, etc. Agent ID = grid position. | ✓ |
| Bracket-grouped, top-to-bottom | Contiguous bracket clusters in the grid. Needs strategy for odd-sized brackets (Degens=20, Doom-Posters=5). | |

**User's choice:** Sequential, row by row

---

## Cell Visual Density

| Option | Description | Selected |
|--------|-------------|----------|
| Color only — pure fill | Solid colored block, no text. Maximally minimalist. | |
| Bracket letter + agent index | 2-char code (Q1, D7) on colored background. Identity at cost of noise. | |
| Confidence as shade | Hue = signal, brightness = confidence. Dense information without text. | ✓ |

**User's choice:** Confidence as shade (brightness encodes confidence 0.0–1.0)

---

**Follow-up: Pending cell appearance**

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed dim gray | Always the same dim gray until a decision arrives. Clear "not yet decided" signal. | ✓ |
| Carry prior round's state | Retain last round's color/shade until overwritten. Could confuse round transitions. | |

**User's choice:** Fixed dim gray

---

## Header Bar Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Status + elapsed + round counter | `[Status] \| Round X/3 \| Elapsed: HH:MM:SS` | ✓ |
| Status + elapsed only | Strictly the two locked fields. Status already encodes round. | |
| Status + elapsed + agent progress | `[Status] \| Round X/3 \| 47/100 agents resolved \| Elapsed` | |

**User's choice:** Status + elapsed + round counter

---

**Follow-up: Seed rumor text in Phase 9?**

| Option | Description | Selected |
|--------|-------------|----------|
| No — defer to Phase 10 | Keep Phase 9 scope tight. Rumor text belongs with the rationale sidebar. | ✓ |
| Yes — truncated in header | Show first ~60 chars of seed rumor in header for context. | |

**User's choice:** No — defer to Phase 10

---

## Claude's Discretion

- Textual component structure, custom CSS, app layout file organization
- asyncio.Lock implementation details for StateStore
- Specific color values and gradient math for confidence-as-brightness
- `tui` subcommand wiring into existing argparse structure

## Deferred Ideas

- Seed rumor text in header — Phase 10
- Agent hover tooltip — not in Phase 9 scope
- Bracket row grouping in grid — Phase 9 uses sequential; could revisit in Phase 10
