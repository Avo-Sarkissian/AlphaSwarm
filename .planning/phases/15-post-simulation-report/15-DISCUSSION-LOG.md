# Phase 15: Post-Simulation Report - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-02
**Phase:** 15-post-simulation-report
**Areas discussed:** ReACT tool dispatch format, Report trigger & TUI integration, Report sections & template approach, Dependency additions

---

## ReACT Tool Dispatch Format

| Option | Description | Selected |
|--------|-------------|----------|
| Structured block | `ACTION: tool_name` + `INPUT: {...}` parsed by line-scan/regex | ✓ |
| Free-text JSON | JSON blob anywhere in LLM output — fragile | |
| XML tags | `<action>` / `<input>` XML wrappers — more complex to prompt | |

**User's choice:** Structured ACTION/INPUT block

---

| Option | Description | Selected |
|--------|-------------|----------|
| FINAL_ANSWER action | Reserved tool name signals loop termination | ✓ |
| DONE keyword in THOUGHT | Scans THOUGHT text — unreliable | |
| Hard cap only | Always runs N iterations — wasteful if agent finishes early | |

**User's choice:** FINAL_ANSWER as reserved action name

---

## Report Trigger & TUI Integration

| Option | Description | Selected |
|--------|-------------|----------|
| CLI only | `alphaswarm report --cycle <id>` standalone subcommand | ✓ |
| TUI auto-trigger | Report generates when SimulationPhase.COMPLETE | |
| TUI button + CLI | Both entry points | |

**User's choice:** CLI only

---

| Option | Description | Selected |
|--------|-------------|----------|
| Ignore TUI 'file path' wording | CLI stdout is enough | |
| Show path in TUI post-run | Sentinel file + TUI footer polling | ✓ |

**User's choice:** Show path in TUI post-run via sentinel file

---

| Option | Description | Selected |
|--------|-------------|----------|
| StateStore + TUI footer | Sentinel `.alphaswarm/last_report.json`, TUI 200ms tick reads it | ✓ |
| New 'Report' footer bar | Dedicated Textual widget — more build work | |

**User's choice:** StateStore + TUI footer (sentinel file polling)

---

## Report Sections & Template Approach

| Option | Description | Selected |
|--------|-------------|----------|
| 4 focused sections | Consensus, brackets, dissenters, entity impact | |
| 4 sections + influence topology | Same + Influence Leaders (5 total) | |
| 6+ sections (full audit) | All of the above + more | ✓ |

**User's choice:** Full audit — 8 sections

---

Additional sections selected (beyond core 4):
- ✓ Influence Leaders
- ✓ Signal Flip Analysis
- ✓ Round-by-Round Timeline
- ✓ Social Post Reach

**Final section list (in order):**
1. Consensus Summary
2. Round-by-Round Timeline
3. Bracket Narratives
4. Key Dissenters
5. Influence Leaders
6. Signal Flip Analysis
7. Entity Impact Analysis
8. Social Post Reach

---

| Option | Description | Selected |
|--------|-------------|----------|
| Jinja2 templates | .j2 template files, clean separation, requires new dependency | ✓ |
| Python f-strings / string.Template | No new dependency, stdlib only | |
| LLM generates markdown | Orchestrator writes final prose — less structured | |

**User's choice:** Jinja2 templates

---

## Dependency Additions

| Option | Description | Selected |
|--------|-------------|----------|
| Add aiofiles | Per REPORT-03 spec, async file write | ✓ |
| Use stdlib asyncio.to_thread | No new dependency | |

**User's choice:** Add aiofiles

---

| Option | Description | Selected |
|--------|-------------|----------|
| ./reports/ directory | Project-relative, git-ignorable, `{cycle_id}_report.md` | ✓ |
| Current working directory | Unpredictable across invocation locations | |
| --output flag only | Explicit but friction for default use | |

**User's choice:** `./reports/` default directory

---

## Claude's Discretion

- Whether Cypher query tools are methods on GraphStateManager or a dedicated ReportQueryEngine class
- ReACT engine module name and file structure
- Jinja2 template organization (master template vs per-section partials)
- ToolObservation data structure (list of dicts vs typed dataclass)
- How TUI polls sentinel file (on_timer vs set_interval tick)
- Whether `--cycle` defaults to most recent completed cycle

## Deferred Ideas

- Interactive report viewer in TUI
- Auto-trigger from TUI on COMPLETE
- HTML/PDF export
- Parameterized report sections (`--sections` flag)
- Hard lock preventing concurrent report + simulation
