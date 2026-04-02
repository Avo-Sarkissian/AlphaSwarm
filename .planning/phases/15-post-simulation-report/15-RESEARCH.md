# Phase 15: Post-Simulation Report - Research

**Researched:** 2026-04-02
**Domain:** ReACT agent loop, Jinja2 templating, async file I/O, Neo4j Cypher reads, CLI subcommand, Textual sentinel polling
**Confidence:** HIGH

## Summary

Phase 15 adds a standalone report-generation pipeline that operates entirely outside the simulation flow. The core is a ReACT (Reason-Act-Observe) engine implemented with prompt-based tool dispatching — the only viable approach because Ollama native tool calling is broken for qwen3.5 (tracked GitHub issues #14493 and #14745, confirmed in STATE.md research decisions). The engine runs a structured Thought-Action-Observation loop capped at 8-10 iterations, dispatching to 8 Cypher query tools that each return typed results for one of the 8 report sections. Assembled sections are rendered through Jinja2 templates and written as markdown via aiofiles.

The structural template for the entire implementation is `interview.py` + `InterviewEngine`: a standalone module with injected `OllamaClient`, async `run()` method, and structlog component-scoped logging. The report engine mirrors this pattern exactly, substituting multi-turn conversation history for a Thought-Action-Observation accumulation list. All 8 Cypher query methods follow the established `session-per-method` + `execute_read` + `_tx` helper pattern already used throughout `graph.py`.

The two new dependencies (`jinja2>=3.1.6` and `aiofiles>=25.1.0`) are already installed in the system Python environment and have well-established, stable APIs. The orchestrator model lifecycle pattern — load → use → unload via `model_manager` — is directly reusable from `seed.py`. The only new project-level infrastructure needed is the `src/alphaswarm/templates/report/` directory for `.j2` files, the `reports/` output directory, and the `.alphaswarm/` sentinel directory.

**Primary recommendation:** Model `report.py` + `ReportEngine` directly on `interview.py` + `InterviewEngine`. Model 8 Cypher read methods directly on `read_agent_interview_context()`. Model the CLI handler directly on `_handle_inject()`. All patterns are in the codebase — this phase is assembly, not invention.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** ReACT tool dispatch uses structured `ACTION`/`INPUT` block format. LLM outputs a literal text block containing `ACTION: <tool_name>` on one line followed by `INPUT: <json>` on the next. Parsed by line-scan or regex — no JSON extraction from prose.

**D-02:** `FINAL_ANSWER` is a reserved tool name. When the LLM emits `ACTION: FINAL_ANSWER`, the loop terminates immediately. No DONE keyword scanning in THOUGHT text.

**D-03:** Hard iteration cap of 8-10. If cap reached without `FINAL_ANSWER`, exit and render with collected observations. Duplicate call detection (same tool + same input twice) counts as termination signal.

**D-04:** CLI-only trigger. `alphaswarm report --cycle <cycle_id>` as a new argparse subcommand following the existing `inject`/`run`/`tui` pattern in `cli.py`.

**D-05:** Sentinel file: `.alphaswarm/last_report.json` containing `{"cycle_id": "...", "path": "./reports/{cycle_id}_report.md", "generated_at": "ISO timestamp"}`. Written by aiofiles.

**D-06:** TUI `_poll_snapshot` (existing 200ms `set_interval`) checks for sentinel file. When found and newer than last tick, `TelemetryFooter` (or `HeaderBar`) displays report path inline. Sentinel file polled, not watched with inotify/FSEvents.

**D-07:** 8 report sections in order: Consensus Summary, Round-by-Round Timeline, Bracket Narratives, Key Dissenters, Influence Leaders, Signal Flip Analysis, Entity Impact Analysis, Social Post Reach.

**D-08:** One Cypher query tool per section = 8 tools total. Tool input always requires `cycle_id`, optional filters per tool.

**D-09:** Jinja2 templates. Each section has a `.j2` template in `src/alphaswarm/templates/report/`. Report assembler renders sections independently, concatenates, and writes to file. Add `jinja2` to `pyproject.toml`.

**D-10:** Default output directory `./reports/`, created by CLI handler if absent. Default filename `{cycle_id}_report.md`. Optional `--output` flag overrides full path.

**D-11:** Async file write via `aiofiles`. Add `aiofiles` to `pyproject.toml`.

**D-12:** Report uses orchestrator model. Serialization is informational warning only (not hard lock) in Phase 15.

### Claude's Discretion

- Whether Cypher query tools live as methods on `GraphStateManager` or in a dedicated `ReportQueryEngine` class
- ReACT engine module name and file location (`report.py` or `react_agent.py`)
- Jinja2 template file structure (one master template vs per-section partials)
- Observation accumulation format (list of dicts, or structured `ToolObservation` dataclass)
- How the TUI polls the sentinel file (in `on_timer` callback vs existing `set_interval` tick method)
- Whether `--cycle` flag is required or defaults to most recent completed cycle (from Neo4j)

### Deferred Ideas (OUT OF SCOPE)

- Interactive report viewer in TUI (scrollable markdown panel) — future v3
- Auto-trigger report on `SimulationPhase.COMPLETE` from TUI — deferred, CLI-only for now
- Report export to HTML or PDF — deferred
- Parameterized report depth — future enhancement
- Hard lock preventing report CLI while TUI simulation is running — informational warning only
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPORT-01 | ReACT-style agent (Thought-Action-Observation loop) queries Neo4j after simulation ends using prompt-based tool dispatching (no Ollama native tools) | D-01/D-02/D-03 dictate exact dispatch format; `InterviewEngine` pattern in `interview.py` is the structural template; `OllamaClient.chat()` direct usage confirmed from Phase 14 |
| REPORT-02 | Cypher query tools for bracket summaries, influence topology analysis, entity-level trends, and signal flip metrics | All 4 domains have existing graph schema: Decision+bracket nodes, INFLUENCED_BY edges, REFERENCES edges to Entity, RationaleEpisode.flip_type; session-per-method pattern established in `graph.py` |
| REPORT-03 | Structured markdown report output with CLI `report` subcommand and file export via aiofiles | `cli.py` argparse subcommand pattern confirmed; `jinja2==3.1.6` and `aiofiles==25.1.0` confirmed latest; `pyproject.toml` dependency additions confirmed; `reports/` output directory pattern matches existing `results/` dir in tui.py |
</phase_requirements>

---

## Project Constraints (from CLAUDE.md)

- **100% async (asyncio):** No blocking I/O on main event loop. Report file writes must use `aiofiles`, not `open()`.
- **Local inference only:** Orchestrator model via Ollama. Report engine calls `OllamaClient.chat()` directly, bypassing `ResourceGovernor`.
- **Memory safety:** `psutil` monitors RAM; governor throttles at 80%, pauses at 90%. Report CLI does not start a governor — it uses orchestrator model sequentially.
- **Max 2 models simultaneously:** Report CLI must not run while TUI simulation is active (worker model loaded). D-12 enforces informational warning only.
- **Python 3.11+ strict typing:** All new code uses `from __future__ import annotations`, `mypy --strict` passes, typed dataclasses for tool outputs.
- **`uv` package manager:** Dependency additions go to `pyproject.toml [project.dependencies]`.
- **`structlog` logging:** Component-scoped logger `structlog.get_logger(component="report")`.
- **`pydantic` for structured data:** Tool output dataclasses should be `frozen=True` per established pattern.
- **`pytest-asyncio` for tests:** `asyncio_mode = "auto"` in `pyproject.toml` — no `@pytest.mark.asyncio` decorator needed.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jinja2 | >=3.1.6 | Section-level template rendering | Latest stable; already installed on system; used by Flask/Sphinx ecosystem |
| aiofiles | >=25.1.0 | Async file writes for report + sentinel | Latest stable; already installed on system; standard async file I/O library |
| ollama | >=0.6.1 (existing) | Orchestrator inference for ReACT loop | Already in `pyproject.toml`; `OllamaClient.chat()` direct usage per Phase 14 pattern |
| neo4j | >=5.28 (existing) | Cypher query tools for all 8 sections | Already in `pyproject.toml`; session-per-method pattern established |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=25.5.0 (existing) | ReACT loop trace logs | Every LLM call + tool dispatch logs `component="report"` |
| pydantic | >=2.12.5 (existing) | ToolObservation dataclass validation | Frozen dataclasses for tool output type safety |
| pathlib | stdlib | Directory creation, path composition | `Path("reports").mkdir(exist_ok=True)`, `Path(".alphaswarm").mkdir(exist_ok=True)` |
| json | stdlib | Sentinel file serialization | `json.dumps({"cycle_id":..., "path":..., "generated_at":...})` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| jinja2 | Python f-string templates | Jinja2 gives clean section boundary, whitespace control, future customization without touching Python |
| aiofiles | asyncio.to_thread(open(...).write) | aiofiles is semantically explicit and standard; `to_thread` would work but obscures intent |
| Per-section .j2 files | Single master .j2 with blocks | Per-section files enable independent rendering and future section reordering without touching master template |

**Installation:**
```bash
uv add "jinja2>=3.1.6" "aiofiles>=25.1.0"
```

**Version verification (confirmed 2026-04-02):**
- `jinja2`: latest = 3.1.6 (confirmed via `pip index versions jinja2`)
- `aiofiles`: latest = 25.1.0 (confirmed via `pip index versions aiofiles`)

---

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
├── report.py                    # ReportEngine (ReACT loop) + ReportAssembler + data types
├── templates/
│   └── report/
│       ├── 01_consensus_summary.j2
│       ├── 02_round_timeline.j2
│       ├── 03_bracket_narratives.j2
│       ├── 04_key_dissenters.j2
│       ├── 05_influence_leaders.j2
│       ├── 06_signal_flip_analysis.j2
│       ├── 07_entity_impact.j2
│       └── 08_social_post_reach.j2
├── graph.py                     # 8 new read methods added
├── cli.py                       # `report` subparser + `_handle_report()` added
└── tui.py                       # sentinel polling added to `_poll_snapshot()`

reports/                         # output directory (git-ignored via .gitignore)
.alphaswarm/                     # sentinel directory (git-ignored)
```

### Pattern 1: ReACT Engine (modeled on InterviewEngine)

**What:** `ReportEngine` class with `OllamaClient` injection, tool registry dict, and async `run(cycle_id)` method that executes the Thought-Action-Observation loop.

**When to use:** When the orchestrator model needs to autonomously decide which tools to call and in what order before finalizing a report.

**Example:**
```python
# Source: interview.py InterviewEngine pattern + D-01/D-02/D-03 locked decisions
import re
import structlog
from dataclasses import dataclass
from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="report")

MAX_ITERATIONS = 10

@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    tool_input: dict  # type: ignore[type-arg]
    result: object    # typed per tool

class ReportEngine:
    def __init__(
        self,
        ollama_client: OllamaClient,
        model: str,
        tools: dict[str, "Callable"],  # tool_name -> async callable
    ) -> None:
        self._client = ollama_client
        self._model = model
        self._tools = tools
        self._log = structlog.get_logger(component="report")

    async def run(self, cycle_id: str) -> list[ToolObservation]:
        observations: list[ToolObservation] = []
        seen_calls: set[tuple[str, str]] = set()  # duplicate detection
        messages = [{"role": "system", "content": REACT_SYSTEM_PROMPT}]

        for iteration in range(MAX_ITERATIONS):
            response = await self._client.chat(
                model=self._model, messages=messages, think=False
            )
            content = response.message.content or ""
            messages.append({"role": "assistant", "content": content})

            # Parse ACTION/INPUT block (D-01)
            action, input_json = _parse_action_input(content)
            if action is None:
                break

            # Termination: FINAL_ANSWER (D-02)
            if action == "FINAL_ANSWER":
                self._log.info("react_final_answer", iteration=iteration)
                break

            # Duplicate call detection (D-03)
            call_key = (action, input_json)
            if call_key in seen_calls:
                self._log.warning("react_duplicate_call", action=action, iteration=iteration)
                break
            seen_calls.add(call_key)

            # Dispatch tool
            tool_fn = self._tools.get(action)
            if tool_fn is None:
                observation_text = f"ERROR: Unknown tool '{action}'"
            else:
                import json
                result = await tool_fn(**json.loads(input_json))
                obs = ToolObservation(tool_name=action, tool_input=json.loads(input_json), result=result)
                observations.append(obs)
                observation_text = str(result)

            messages.append({"role": "user", "content": f"OBSERVATION: {observation_text}"})
            self._log.debug("react_step", iteration=iteration, action=action)

        return observations
```

### Pattern 2: Cypher Query Tool (modeled on read_agent_interview_context)

**What:** Async method on `GraphStateManager` that opens a session, calls `execute_read` with a `_tx` helper, returns a typed Pydantic/dataclass result.

**When to use:** All 8 report section queries — keeps all Cypher in `graph.py`, consistent with established session-per-method pattern.

**Example (Consensus Summary tool):**
```python
# Source: graph.py read_peer_decisions() + read_agent_interview_context() patterns
async def read_consensus_summary(self, cycle_id: str) -> ConsensusSummary:
    """Count BUY/SELL/HOLD decisions in Round 3 for cycle (REPORT-02)."""
    try:
        async with self._driver.session(database=self._database) as session:
            record = await session.execute_read(
                self._read_consensus_summary_tx, cycle_id
            )
    except Neo4jError as exc:
        raise Neo4jConnectionError(
            f"Failed to read consensus summary for cycle {cycle_id}",
            original_error=exc,
        ) from exc
    return ConsensusSummary(**record)

@staticmethod
async def _read_consensus_summary_tx(
    tx: AsyncManagedTransaction, cycle_id: str
) -> dict:  # type: ignore[type-arg]
    result = await tx.run(
        """
        MATCH (d:Decision {cycle_id: $cycle_id, round: 3})
        RETURN
            sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
            sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
            sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count,
            count(d) AS total
        """,
        cycle_id=cycle_id,
    )
    record = await result.single()
    return dict(record) if record else {"buy_count": 0, "sell_count": 0, "hold_count": 0, "total": 0}
```

### Pattern 3: Jinja2 Template Rendering

**What:** `Environment` with `FileSystemLoader` pointing at `src/alphaswarm/templates/report/`. Each section template is rendered independently with its observation data, then results are concatenated.

**When to use:** Report assembler renders each of the 8 sections.

**Example:**
```python
# Source: Jinja2 3.1.6 official docs — Environment + FileSystemLoader pattern
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates" / "report"

def _make_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,  # Markdown output, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )

async def assemble_report(
    observations: list[ToolObservation],
    cycle_id: str,
) -> str:
    env = _make_jinja_env()
    sections: list[str] = []
    for obs in observations:
        template_name = TOOL_TO_TEMPLATE[obs.tool_name]
        template = env.get_template(template_name)
        rendered = template.render(data=obs.result, cycle_id=cycle_id)
        sections.append(rendered)
    return "\n\n".join(sections)
```

### Pattern 4: aiofiles Async Write

**What:** `aiofiles.open()` async context manager for sentinel file and report file writes.

**When to use:** Both the report markdown write and the sentinel JSON write in `_handle_report()`.

**Example:**
```python
# Source: aiofiles 25.1.0 official API
import aiofiles
import json
from pathlib import Path

async def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)

async def write_sentinel(cycle_id: str, report_path: str) -> None:
    sentinel_dir = Path(".alphaswarm")
    sentinel_dir.mkdir(exist_ok=True)
    sentinel = {
        "cycle_id": cycle_id,
        "path": report_path,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    async with aiofiles.open(sentinel_dir / "last_report.json", "w") as f:
        await f.write(json.dumps(sentinel, indent=2))
```

### Pattern 5: CLI Subcommand (modeled on inject/run pattern)

**What:** New `report` subparser in `cli.py:main()`, with `_handle_report(cycle_id, output)` async handler wrapped in `asyncio.run()`.

**When to use:** The `alphaswarm report --cycle <cycle_id>` entry point.

**Example:**
```python
# Source: cli.py main() lines 633-684 (inject/run subparser pattern)
# In main():
report_parser = subparsers.add_parser("report", help="Generate post-simulation analysis report")
report_parser.add_argument("--cycle", type=str, required=True, help="Cycle ID to report on")
report_parser.add_argument("--output", type=str, default=None, help="Override output file path")

# Handler (follows _handle_inject async pattern):
async def _handle_report(cycle_id: str, output: str | None) -> None:
    settings = AppSettings()
    app = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    # warn if potential model collision
    # load orchestrator model
    # run ReportEngine
    # assemble + render via Jinja2
    # write report via aiofiles
    # write sentinel via aiofiles
    # print report path
    await app.graph_manager.close()
```

### Pattern 6: Sentinel File Polling in TUI

**What:** Add sentinel file stat check inside existing `_poll_snapshot()` method. Compare `mtime` of `.alphaswarm/last_report.json` against a stored `_last_sentinel_mtime`. When newer, call `TelemetryFooter.update_report_path(path)` or append to `HeaderBar` text.

**When to use:** Inside `_poll_snapshot()` — runs on the existing 200ms `set_interval` tick, no new timer needed.

**Example:**
```python
# Source: tui.py _poll_snapshot() (lines 834-880) — existing pattern
# Add to _poll_snapshot() after existing updates:
sentinel_path = Path(".alphaswarm") / "last_report.json"
if sentinel_path.exists():
    mtime = sentinel_path.stat().st_mtime
    if mtime > self._last_sentinel_mtime:
        self._last_sentinel_mtime = mtime
        import json
        data = json.loads(sentinel_path.read_text())
        self._telemetry_footer.update_report_path(data["path"])
```

Note: `_poll_snapshot` is a sync method — `sentinel_path.stat()` and `read_text()` are acceptable here since they are fast filesystem reads on local disk, consistent with existing sync `snapshot()` call pattern.

### Anti-Patterns to Avoid

- **Calling `open()` for file writes:** Use `aiofiles.open()` in async context. Plain `open()` blocks the event loop.
- **Parsing ACTION/INPUT from arbitrary prose positions:** Parse only the first occurrence. LLMs may emit THOUGHT text before the ACTION block — scan forward for the `ACTION:` line.
- **Creating a new `set_interval` timer in TUI for sentinel polling:** Hook into existing `_poll_snapshot()` to avoid multiple timers competing.
- **Running report engine concurrently with agent interviews:** Both use orchestrator and worker models respectively. D-12 enforces warning only, but plan must document the serialization requirement.
- **Per-request `num_ctx` in Ollama calls:** Existing `OllamaClient.chat()` does not pass `num_ctx` per-request (INFRA-04). Report engine must follow same pattern.
- **Jinja2 `autoescape=True` for markdown output:** Autoescape is for HTML. Markdown output must use `autoescape=False` or the `|` markdown pipe character will be escaped.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Template rendering | Python f-string concatenation for 8 sections | `jinja2.Environment` with `FileSystemLoader` | Whitespace control, conditional blocks, loop iteration, future section customization without Python changes |
| Async file I/O | `asyncio.to_thread(lambda: open(...).write(...))` | `aiofiles.open()` | Semantically explicit, well-tested, directly supported async API |
| ACTION/INPUT parsing | Full JSON extractor from prose | Line-scan regex `^ACTION:\s*(.+)` + `^INPUT:\s*(.+)` | LLM prose is unpredictable; structured line-scan is testable and matches D-01 decision |
| Duplicate call detection | Complex state machine | `set[tuple[str, str]]` of `(tool_name, json_str)` | Simple, O(1), covers all duplicate patterns |
| Sentinel file watching | FSEvents / inotify watcher | `Path.stat().st_mtime` poll in existing 200ms tick | No extra dependencies, matches D-06 decision, avoids platform-specific watcher APIs |

**Key insight:** The heavy lifting (Cypher query patterns, OllamaClient lifecycle, Jinja2 rendering, aiofiles writes) is all solved. This phase is wiring established patterns into a new module — `report.py` is structurally a near-copy of `interview.py` with a tool registry replacing conversation history.

---

## Runtime State Inventory

> This phase does not rename or refactor existing state. Skip section — no runtime state changes.

---

## Common Pitfalls

### Pitfall 1: INFLUENCED_BY edge double-counting across rounds
**What goes wrong:** Querying `MATCH (a)-[inf:INFLUENCED_BY {cycle_id: $cycle_id}]->(b)` without a round filter returns multiple edges between the same pair (one per round per D-07 in graph.py comments: "Multiple edges between the same pair across different rounds are expected").
**Why it happens:** `compute_influence_edges()` runs after each round and CREATEs (not MERGEs) new edges. Round 3 cumulative result = 3x edges per pair.
**How to avoid:** Always filter with `round: 3` (or the desired round) in INFLUENCED_BY queries. For Influence Leaders (cumulative), SUM weights grouped by target across all rounds, or query round 3 edges only.
**Warning signs:** Agent appearing in influence leaders with weight > 1.0 (normalized weight can't exceed 1.0 per total_agents normalization).

### Pitfall 2: RationaleEpisode.flip_type is stored as string value, not enum
**What goes wrong:** Comparing `re.flip_type = 'FlipType.HOLD_TO_BUY'` fails because the stored value is the `.value` (e.g., `'HOLD_TO_BUY'`), not the Python enum repr.
**Why it happens:** Phase 11 decision: "EpisodeRecord.flip_type stored as str (FlipType.value) for zero-cost Neo4j property assignment."
**How to avoid:** Signal Flip Analysis Cypher must filter `WHERE re.flip_type <> 'NONE'` (string comparison), not enum comparison.
**Warning signs:** Signal flip query returns 0 results even though flips occurred during simulation.

### Pitfall 3: Jinja2 FileSystemLoader path at runtime vs editable install
**What goes wrong:** `Path(__file__).parent / "templates" / "report"` resolves correctly during editable install but may fail if package is built and installed without `templates/` directory included in the wheel manifest.
**Why it happens:** `hatchling` build backend requires explicit `include` configuration to package non-.py files.
**How to avoid:** Verify `pyproject.toml` `[tool.hatch.build.targets.wheel]` includes `src/alphaswarm/templates/**`. In development (editable install), `__file__`-relative paths always work.
**Warning signs:** `jinja2.exceptions.TemplateNotFound` in non-editable installs. No impact in current dev workflow.

### Pitfall 4: aiofiles write in sync CLI handler
**What goes wrong:** Calling `await write_report(...)` from a sync function.
**Why it happens:** `_handle_report` must be async and wrapped in `asyncio.run()` in `main()`, matching the `_handle_inject` pattern. If defined as sync and aiofiles write called directly, `RuntimeError: no running event loop`.
**How to avoid:** Follow exact pattern from `_handle_inject` — define handler as `async def _handle_report(...)`, call from `main()` via `asyncio.run(_handle_report(...))`.

### Pitfall 5: TUI sentinel polling causes "object referenced before assignment" on first tick
**What goes wrong:** `_last_sentinel_mtime` instance variable not initialized in `AlphaSwarmApp.__init__()`.
**Why it happens:** Sentinel file may not exist on first poll. `Path.exists()` guard prevents the crash, but `self._last_sentinel_mtime` must exist before `_poll_snapshot()` runs.
**How to avoid:** Initialize `self._last_sentinel_mtime: float = 0.0` in `AlphaSwarmApp.__init__()`.
**Warning signs:** `AttributeError: 'AlphaSwarmApp' object has no attribute '_last_sentinel_mtime'` on TUI startup.

### Pitfall 6: ReACT prompt output reliability
**What goes wrong:** qwen3.5:32b emits THOUGHT text that contains "ACTION:" as part of reasoning prose, not as a tool call. Parser fires prematurely.
**Why it happens:** LLM may write "I should call ACTION: bracket_summary" in thought prose. Line-scan hits this before the real ACTION block.
**How to avoid:** Look for `ACTION:` lines not preceded by THOUGHT content on the same line. Parse ONLY lines that start with `^ACTION:` (beginning of line) after stripping leading whitespace. The structured block format (D-01) relies on ACTION being on its own line.
**Warning signs:** Tool dispatch fires with tool name containing spaces or long strings — signals it parsed prose, not a structured block.

---

## Code Examples

Verified patterns from existing codebase:

### ReACT System Prompt Structure
```
# Source: D-01/D-02/D-03 decisions + "Specific Ideas" in CONTEXT.md
REACT_SYSTEM_PROMPT = """
You are a financial market analysis agent. You have access to the following tools:

- bracket_summary: Get BUY/SELL/HOLD breakdown per bracket for Round 3
- round_timeline: Get global signal percentages across Rounds 1, 2, and 3
- bracket_narratives: Get dominant signal and avg confidence per bracket
- key_dissenters: Get agents whose Round 3 signal diverges from their bracket majority
- influence_leaders: Get top agents by cumulative INFLUENCED_BY edge weight
- signal_flip_analysis: Get agents who changed position between rounds
- entity_impact: Get per-entity sentiment aggregation via REFERENCES edges
- social_post_reach: Get top posts by READ_POST edge count
- FINAL_ANSWER: Signal that you have gathered enough data to write the report

For each step, output EXACTLY:
THOUGHT: <your reasoning>
ACTION: <tool_name>
INPUT: {"cycle_id": "<cycle_id>", ...optional filters}

When you have gathered sufficient observations, output:
ACTION: FINAL_ANSWER
INPUT: {}
"""
```

### ACTION/INPUT Parser (D-01 line-scan)
```python
# Source: D-01 decision — "parsed by line-scan or regex"
import re

_ACTION_RE = re.compile(r"^ACTION:\s*(.+)$", re.MULTILINE)
_INPUT_RE = re.compile(r"^INPUT:\s*(.+)$", re.MULTILINE)

def _parse_action_input(content: str) -> tuple[str | None, str | None]:
    """Extract first ACTION and INPUT values from LLM output."""
    action_match = _ACTION_RE.search(content)
    input_match = _INPUT_RE.search(content)
    if action_match is None:
        return None, None
    action = action_match.group(1).strip()
    input_json = input_match.group(1).strip() if input_match else "{}"
    return action, input_json
```

### Jinja2 Section Template Example (01_consensus_summary.j2)
```jinja2
{# Source: Jinja2 3.1.6 official docs — trim_blocks=True, lstrip_blocks=True #}
## Consensus Summary

**Cycle:** {{ cycle_id }}

| Signal | Count | Share |
|--------|-------|-------|
| BUY    | {{ data.buy_count }} | {{ "%.1f"|format(data.buy_count / data.total * 100) }}% |
| SELL   | {{ data.sell_count }} | {{ "%.1f"|format(data.sell_count / data.total * 100) }}% |
| HOLD   | {{ data.hold_count }} | {{ "%.1f"|format(data.hold_count / data.total * 100) }}% |

**Total agents:** {{ data.total }}
```

### Cypher Query: Key Dissenters (Section 4)
```cypher
-- Source: graph.py OPTIONAL MATCH pattern from read_agent_interview_context()
-- Requires: Decision nodes with (cycle_id, round, bracket, signal) properties
MATCH (a:Agent)-[:HAS_DECISION]->(d:Decision {cycle_id: $cycle_id, round: 3})
WITH a.bracket AS bracket,
     collect({agent_id: a.id, signal: d.signal, name: a.name}) AS agents
WITH bracket, agents,
     [x IN agents | x.signal] AS signals,
     [sig IN ['BUY','SELL','HOLD'] |
       {sig: sig, cnt: size([x IN agents WHERE x.signal = sig])}
     ] AS counts
WITH bracket, agents,
     reduce(best = {sig:'', cnt:0}, x IN counts |
       CASE WHEN x.cnt > best.cnt THEN x ELSE best END
     ).sig AS majority
UNWIND agents AS agent
WHERE agent.signal <> majority
RETURN agent.agent_id AS agent_id, agent.name AS name,
       bracket, agent.signal AS signal, majority AS bracket_majority
ORDER BY bracket
```

### Cypher Query: Influence Leaders (Section 5)
```cypher
-- Source: graph.py compute_influence_edges() — INFLUENCED_BY edge schema
-- Note: Filter by round=3 to avoid double-counting (Pitfall 1)
MATCH (src:Agent)-[inf:INFLUENCED_BY {cycle_id: $cycle_id, round: 3}]->(tgt:Agent)
RETURN tgt.id AS agent_id,
       tgt.name AS name,
       tgt.bracket AS bracket,
       sum(inf.weight) AS total_influence_weight,
       count(src) AS citation_count
ORDER BY total_influence_weight DESC
LIMIT $limit
```

### Cypher Query: Signal Flip Analysis (Section 6)
```cypher
-- Source: Phase 11 D-05 — flip_type stored as FlipType.value string
MATCH (a:Agent)-[:HAS_DECISION]->(d:Decision {cycle_id: $cycle_id})
MATCH (d)-[:HAS_EPISODE]->(re:RationaleEpisode)
WHERE re.flip_type <> 'NONE'
RETURN a.id AS agent_id,
       a.name AS name,
       a.bracket AS bracket,
       re.round AS round_num,
       re.flip_type AS flip_type,
       d.signal AS final_signal
ORDER BY re.round, a.bracket
```

### Cypher Query: Entity Impact Analysis (Section 7)
```cypher
-- Source: Phase 11 GRAPH-03 — REFERENCES edges from Decision to Entity
MATCH (d:Decision {cycle_id: $cycle_id})-[:REFERENCES]->(e:Entity)
RETURN e.name AS entity_name,
       e.type AS entity_type,
       avg(d.sentiment) AS avg_sentiment,
       count(d) AS mention_count,
       sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_mentions,
       sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_mentions,
       sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_mentions
ORDER BY mention_count DESC
```

### Cypher Query: Social Post Reach (Section 8)
```cypher
-- Source: Phase 12 SOCIAL-01 — READ_POST edges from Agent to Post
MATCH (a:Agent)-[:READ_POST {cycle_id: $cycle_id}]->(p:Post)
WITH p, count(a) AS reader_count
MATCH (author:Agent {id: p.agent_id})
RETURN p.post_id AS post_id,
       author.name AS author_name,
       author.bracket AS bracket,
       p.signal AS signal,
       p.round_num AS round_num,
       p.content AS content,
       reader_count
ORDER BY reader_count DESC
LIMIT $limit
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Ollama native tool calling | Prompt-based ACTION/INPUT dispatch | Phase 14 research (GitHub #14493, #14745) | ReACT loop must parse structured text blocks, not function call responses |
| Blocking file writes | aiofiles async writes | Phase 15 (new) | No event loop blocking for report/sentinel file writes |
| Inline f-string report formatting | Jinja2 per-section templates | Phase 15 (new) | Clean Python/template boundary, future section customization without Python changes |

**Deprecated/outdated:**
- Ollama `tools=` parameter for qwen3.5 models: broken, do not use. Prompt-based dispatching is the only reliable approach.
- `results/` directory (used by TUI `action_save_results`): Phase 15 uses `reports/` as the canonical output directory for full structured reports. The `results/` directory remains for the TUI quick-save feature.

---

## Open Questions

1. **HAS_DECISION edge name**
   - What we know: `read_agent_interview_context()` uses a multi-hop Cypher pattern involving Agent and Decision nodes. The exact relationship name used in `_read_interview_context_tx` was not fully read.
   - What's unclear: The Cypher for Cypher query tools needs the exact relationship name between Agent and Decision nodes.
   - Recommendation: Read `graph.py:_read_interview_context_tx` (line ~1059) and `_batch_write_decisions_tx` (line ~329) to confirm the edge name before writing Cypher for sections 1-4.

2. **Decision node properties: `round` vs `round_num`**
   - What we know: `SCHEMA_STATEMENTS` indexes on `(d.cycle_id, d.round)`. `RankedPost` dataclass uses `round_num`.
   - What's unclear: Decision nodes use property `round` (based on index), Posts use `round_num`. Cypher queries must use the correct property name per node type.
   - Recommendation: Verify Decision property name in `_batch_write_decisions_tx` before writing Round-by-Round Timeline query (Section 2).

3. **Whether `--cycle` should default to most recent cycle**
   - What we know: D-04 requires `--cycle <cycle_id>` subcommand. Claude's Discretion allows defaulting to most recent completed cycle.
   - What's unclear: This requires a "get most recent cycle_id" Cypher query on the Cycle node.
   - Recommendation: Make `--cycle` optional, default to most recent. Add `read_latest_cycle_id()` as a simple Cypher read on `MATCH (c:Cycle) RETURN c.cycle_id ORDER BY c.created_at DESC LIMIT 1`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| jinja2 | Section template rendering | system Python | 3.1.5 (system) / 3.1.6 PyPI | — |
| aiofiles | Async report + sentinel writes | system Python | 25.1.0 (system) | — |
| Neo4j (Docker) | All 8 Cypher query tools | must be running at report time | 5.x | — |
| Ollama | Orchestrator ReACT loop inference | must be running at report time | existing | — |

**Note on jinja2/aiofiles:** Both are installed in system Python. They are NOT yet in `pyproject.toml` as project dependencies. Adding them to `[project.dependencies]` is required for the uv-managed venv to include them.

**Missing dependencies with no fallback:**
- None. All required packages are installable via `uv add`.

**Missing dependencies with fallback:**
- None.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_report.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPORT-01 | ReACT loop terminates on FINAL_ANSWER | unit | `pytest tests/test_report.py::TestReportEngine::test_terminates_on_final_answer -x` | Wave 0 |
| REPORT-01 | ReACT loop terminates at iteration cap (10) | unit | `pytest tests/test_report.py::TestReportEngine::test_hard_cap_termination -x` | Wave 0 |
| REPORT-01 | Duplicate call detection terminates loop | unit | `pytest tests/test_report.py::TestReportEngine::test_duplicate_call_terminates -x` | Wave 0 |
| REPORT-01 | ACTION/INPUT parser extracts correct values | unit | `pytest tests/test_report.py::TestParseActionInput -x` | Wave 0 |
| REPORT-02 | `read_consensus_summary()` returns typed result | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_read_consensus_summary -x` | Wave 0 |
| REPORT-02 | `read_influence_leaders()` filters by round to avoid double-count | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_influence_leaders_round_filter -x` | Wave 0 |
| REPORT-02 | `read_signal_flips()` filters flip_type != 'NONE' | unit | `pytest tests/test_report.py::TestGraphQueryTools::test_signal_flip_none_filter -x` | Wave 0 |
| REPORT-03 | Jinja2 renders section from observation data | unit | `pytest tests/test_report.py::TestReportAssembler::test_renders_section -x` | Wave 0 |
| REPORT-03 | Report file written via aiofiles | unit | `pytest tests/test_report.py::TestReportAssembler::test_async_file_write -x` | Wave 0 |
| REPORT-03 | Sentinel file written with correct schema | unit | `pytest tests/test_report.py::TestReportAssembler::test_sentinel_file_schema -x` | Wave 0 |
| REPORT-03 | CLI `report` subcommand registered in argparse | unit | `pytest tests/test_cli.py::test_report_subcommand_registered -x` | Wave 0 |
| REPORT-03 | TUI polls sentinel and updates TelemetryFooter | unit | `pytest tests/test_tui.py::test_sentinel_poll_updates_footer -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_report.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_report.py` — covers REPORT-01, REPORT-02, REPORT-03 (new file)
- [ ] `tests/test_report.py` — needs `mock_driver` fixture (importable from `test_graph.py` pattern or re-declared)
- [ ] `src/alphaswarm/templates/report/*.j2` — 8 template files (new directory)
- [ ] `src/alphaswarm/report.py` — new module (new file)
- [ ] `pyproject.toml` — add `jinja2>=3.1.6` and `aiofiles>=25.1.0` to `[project.dependencies]`

---

## Sources

### Primary (HIGH confidence)
- Codebase — `src/alphaswarm/interview.py` (InterviewEngine structural template, OllamaClient.chat() direct usage pattern)
- Codebase — `src/alphaswarm/graph.py` (session-per-method pattern, INFLUENCED_BY schema, REFERENCES schema, RationaleEpisode.flip_type = str value, READ_POST edges)
- Codebase — `src/alphaswarm/cli.py` lines 633-699 (argparse subcommand pattern, asyncio.run() wrapping, handler structure)
- Codebase — `src/alphaswarm/tui.py` lines 834-880 (`_poll_snapshot()` existing timer callback, `TelemetryFooter` widget)
- Codebase — `src/alphaswarm/seed.py` (orchestrator model lifecycle: load → use → unload via model_manager)
- Codebase — `pyproject.toml` (confirmed missing jinja2/aiofiles from project dependencies)
- `.planning/phases/15-post-simulation-report/15-CONTEXT.md` (all locked decisions D-01 through D-12)
- `.planning/STATE.md` (confirmed: Ollama native tool calling broken for qwen3.5, orchestrator model 30s swap, all Phase 11/12 graph schema decisions)

### Secondary (MEDIUM confidence)
- `pip index versions jinja2` — confirmed 3.1.6 is latest stable (2026-04-02)
- `pip index versions aiofiles` — confirmed 25.1.0 is latest stable (2026-04-02)
- Jinja2 3.1.x `Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)` — stable API since 3.0, no breaking changes in 3.1.x series

### Tertiary (LOW confidence)
- None.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — jinja2 and aiofiles versions confirmed via PyPI; existing stack is project-established
- Architecture: HIGH — all patterns directly observable in existing codebase; no external research required
- Pitfalls: HIGH — Pitfalls 1-5 verified against actual graph.py code; Pitfall 6 derived from STATE.md research decision on ReACT output reliability

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable libraries; jinja2/aiofiles APIs change slowly)
