"""ReACT report engine and data types for post-simulation analysis."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import aiofiles
import structlog
from jinja2 import Environment, FileSystemLoader

if TYPE_CHECKING:
    from alphaswarm.ollama_client import OllamaClient

from alphaswarm.charts import (
    render_bracket_breakdown,
    render_consensus_bar,
    render_round_timeline,
    render_ticker_consensus,
)

log = structlog.get_logger(component="report")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10

REACT_SYSTEM_PROMPT = """\
You are a post-simulation market analysis agent. Your task is to query the \
simulation graph and produce a comprehensive structured analysis report.

Available tools:
- consensus_summary: Get global BUY/SELL/HOLD breakdown for Round 3
- round_timeline: Get signal distribution per round (rounds 1-3)
- bracket_narratives: Get per-bracket stance summary for Round 3
- key_dissenters: Find agents whose signal diverges from bracket majority in Round 3
- influence_leaders: Get top agents by INFLUENCED_BY edge weight
- signal_flips: Get agents who changed position between rounds
- entity_impact: Get per-entity sentiment aggregation
- social_post_reach: Get top posts by READ_POST edge count
- FINAL_ANSWER: Signal that you have gathered enough data and are done

For each step, output exactly this format:
THOUGHT: <your reasoning>
ACTION: <tool_name>
INPUT: <json with cycle_id and any optional params>

When you have gathered all necessary data, output:
THOUGHT: I have gathered all the data I need.
ACTION: FINAL_ANSWER
INPUT: {}
"""

# ---------------------------------------------------------------------------
# Regex patterns for ACTION/INPUT parsing (D-01)
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(r"^ACTION:\s*(.+)$", re.MULTILINE)
_INPUT_RE = re.compile(r"^INPUT:\s*(.+)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolObservation:
    """Immutable record of a single tool call and its result in the ReACT loop."""

    tool_name: str
    tool_input: dict[str, object]
    result: object


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_action_input(content: str) -> tuple[str | None, str | None]:
    """Extract ACTION and INPUT from LLM output structured block (D-01).

    Scans the content string for ACTION and INPUT lines using regex.
    Returns (None, None) if no ACTION line found.
    Returns (action, "{}") if ACTION found but no INPUT line.

    Args:
        content: Raw LLM response content.

    Returns:
        Tuple of (action_name, input_json_string) or (None, None).
    """
    action_match = _ACTION_RE.search(content)
    if action_match is None:
        return None, None

    action = action_match.group(1).strip()

    input_match = _INPUT_RE.search(content)
    input_json = input_match.group(1).strip() if input_match else "{}"

    return action, input_json


# ---------------------------------------------------------------------------
# ReACT Engine
# ---------------------------------------------------------------------------


class ReportEngine:
    """ReACT (Reason-Act-Observe) engine for post-simulation report generation.

    Implements a Thought-Action-Observation loop with 3 termination modes:
    1. FINAL_ANSWER action (D-02)
    2. Hard iteration cap at MAX_ITERATIONS (D-03)
    3. Duplicate (tool, input) call detection (D-03)

    Per D-12: Does NOT manage model lifecycle — that is the CLI handler's job.
    """

    def __init__(
        self,
        ollama_client: OllamaClient,
        model: str,
        tools: dict[str, Callable],  # type: ignore[type-arg]
    ) -> None:
        self._client = ollama_client
        self._model = model
        self._tools = tools
        self._log = structlog.get_logger(component="report")

    async def run(self, cycle_id: str) -> list[ToolObservation]:
        """Execute the ReACT loop and return accumulated tool observations.

        Args:
            cycle_id: The simulation cycle ID to generate a report for.

        Returns:
            List of ToolObservation records from successful tool dispatches.
        """
        observations: list[ToolObservation] = []
        seen_calls: set[tuple[str, str]] = set()

        messages: list[dict[str, str]] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Generate a comprehensive post-simulation analysis report "
                    f"for cycle {cycle_id}. Begin by gathering data."
                ),
            },
        ]

        for iteration in range(MAX_ITERATIONS):
            response = await self._client.chat(
                model=self._model, messages=messages, think=False,
            )
            content = response.message.content or ""
            messages.append({"role": "assistant", "content": content})

            # Parse ACTION/INPUT block (D-01)
            action, input_json = _parse_action_input(content)
            if action is None:
                self._log.warning("no_action_parsed", iteration=iteration)
                break

            # Termination: FINAL_ANSWER (D-02)
            if action == "FINAL_ANSWER":
                self._log.info("react_final_answer", iteration=iteration)
                break

            # Duplicate call detection (D-03)
            call_key = (action, input_json or "{}")
            if call_key in seen_calls:
                self._log.warning(
                    "react_duplicate_call", action=action, iteration=iteration,
                )
                break
            seen_calls.add(call_key)

            # Dispatch tool
            tool_fn = self._tools.get(action)
            if tool_fn is None:
                observation_text = f"ERROR: Unknown tool '{action}'"
                messages.append({"role": "user", "content": f"OBSERVATION: {observation_text}"})
                continue

            parsed_input: dict[str, object] = json.loads(input_json or "{}")
            result = await tool_fn(**parsed_input)
            obs = ToolObservation(
                tool_name=action,
                tool_input=parsed_input,
                result=result,
            )
            observations.append(obs)

            messages.append({"role": "user", "content": f"OBSERVATION: {str(result)}"})
            self._log.debug("react_step", iteration=iteration, action=action)

        self._log.info(
            "react_complete",
            total_iterations=min(iteration + 1, MAX_ITERATIONS),
            observation_count=len(observations),
        )
        return observations


# ---------------------------------------------------------------------------
# Report Assembly (Plan 02)
# ---------------------------------------------------------------------------

TEMPLATE_DIR = Path(__file__).parent / "templates" / "report"

TOOL_TO_TEMPLATE: dict[str, str] = {
    "bracket_summary": "01_consensus_summary.j2",
    "round_timeline": "02_round_timeline.j2",
    "bracket_narratives": "03_bracket_narratives.j2",
    "key_dissenters": "04_key_dissenters.j2",
    "influence_leaders": "05_influence_leaders.j2",
    "signal_flip_analysis": "06_signal_flip_analysis.j2",
    "entity_impact": "07_entity_impact.j2",
    "social_post_reach": "08_social_post_reach.j2",
    "portfolio_impact": "10_portfolio_impact.j2",
}

# Canonical section order for assembling the report (D-07)
SECTION_ORDER: list[str] = [
    "bracket_summary",
    "round_timeline",
    "bracket_narratives",
    "key_dissenters",
    "influence_leaders",
    "signal_flip_analysis",
    "entity_impact",
    "social_post_reach",
    "portfolio_impact",
]


class ReportAssembler:
    """Jinja2-based assembler for post-simulation analysis reports.

    Renders each section from a ToolObservation list and concatenates them
    into a single markdown document in canonical SECTION_ORDER.
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,  # markdown output, not HTML (per RESEARCH anti-pattern note)
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_section(
        self,
        template_name: str,
        *,
        data: object,
        cycle_id: str,
    ) -> str:
        """Render a single section template with data and cycle_id context.

        Args:
            template_name: Filename of the Jinja2 template (e.g. '01_consensus_summary.j2').
            data: The tool result data to pass as `data` in the template context.
            cycle_id: The simulation cycle ID.

        Returns:
            Rendered markdown string for this section.
        """
        template = self._env.get_template(template_name)
        return template.render(data=data, cycle_id=cycle_id)

    def assemble(self, observations: list[ToolObservation], cycle_id: str) -> str:
        """Assemble all observations into a complete markdown report document.

        Observations are ordered by SECTION_ORDER (may arrive out of order from ReACT).
        Sections not present in observations are silently skipped.

        Args:
            observations: List of tool observations from ReportEngine.run().
            cycle_id: The simulation cycle ID.

        Returns:
            Complete markdown report string with header and all sections.
        """
        # Index observations by tool_name for fast lookup
        obs_by_tool: dict[str, ToolObservation] = {obs.tool_name: obs for obs in observations}

        now_iso = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        header = (
            f"# Post-Simulation Analysis Report\n\n"
            f"**Cycle:** {cycle_id}\n"
            f"**Generated:** {now_iso}\n\n"
            f"---\n\n"
        )

        sections: list[str] = []
        for tool_name in SECTION_ORDER:
            obs = obs_by_tool.get(tool_name)
            if obs is None:
                continue
            template_name = TOOL_TO_TEMPLATE.get(tool_name)
            if template_name is None:
                continue
            rendered = self.render_section(template_name, data=obs.result, cycle_id=cycle_id)
            sections.append(rendered)

        return header + "\n\n".join(sections)

    def assemble_html(
        self,
        observations: list[ToolObservation],
        cycle_id: str,
        *,
        market_context_data: list[dict] | None = None,  # type: ignore[type-arg]
    ) -> str:
        """Assemble observations into a self-contained HTML report.

        Uses a separate Jinja2 Environment with autoescape=True for HTML safety.
        SVG strings from chart builders are passed through |safe filter in template.

        Args:
            observations: List of tool observations from ReportEngine.run().
            cycle_id: The simulation cycle ID.
            market_context_data: Optional per-ticker market + consensus dicts.

        Returns:
            Complete self-contained HTML string.
        """
        html_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        obs_by_tool: dict[str, ToolObservation] = {obs.tool_name: obs for obs in observations}

        # Generate SVG charts from observation data
        consensus_svg = ""
        if "bracket_summary" in obs_by_tool:
            consensus_svg = render_consensus_bar(obs_by_tool["bracket_summary"].result)  # type: ignore[arg-type]

        timeline_svg = ""
        if "round_timeline" in obs_by_tool:
            timeline_svg = render_round_timeline(obs_by_tool["round_timeline"].result)  # type: ignore[arg-type]

        bracket_svg = ""
        if "bracket_narratives" in obs_by_tool:
            bracket_svg = render_bracket_breakdown(obs_by_tool["bracket_narratives"].result)  # type: ignore[arg-type]

        # Ticker mini-charts — up to 3 tickers
        ticker_svgs: list[str] = []
        if market_context_data:
            for ticker_row in market_context_data[:3]:
                svg = render_ticker_consensus(ticker_row)
                if svg:
                    ticker_svgs.append(svg)

        # Build sections dict for data tables
        sections: dict[str, object] = {obs.tool_name: obs.result for obs in observations}

        now_iso = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

        template = html_env.get_template("report.html.j2")
        return template.render(
            cycle_id=cycle_id,
            generated_at=now_iso,
            consensus_svg=consensus_svg,
            timeline_svg=timeline_svg,
            bracket_svg=bracket_svg,
            ticker_svgs=ticker_svgs,
            sections=sections,
            market_context_data=market_context_data or [],
        )


async def write_report(path: Path, content: str) -> None:
    """Write report content to disk using aiofiles (async, per D-11).

    Creates parent directory if absent (per D-10).

    Args:
        path: Destination file path.
        content: Markdown content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)


async def write_sentinel(
    cycle_id: str,
    report_path: str,
    *,
    sentinel_dir: Path | None = None,
) -> None:
    """Write sentinel JSON file for TUI polling (per D-05).

    Creates .alphaswarm/last_report.json (or sentinel_dir/last_report.json
    when sentinel_dir is provided for test injection).

    Args:
        cycle_id: The simulation cycle ID.
        report_path: String path to the generated report file.
        sentinel_dir: Override sentinel directory (default: Path('.alphaswarm')).
    """
    directory = sentinel_dir if sentinel_dir is not None else Path(".alphaswarm")
    directory.mkdir(parents=True, exist_ok=True)
    sentinel_file = directory / "last_report.json"
    payload = {
        "cycle_id": cycle_id,
        "path": report_path,
        "generated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    }
    async with aiofiles.open(sentinel_file, "w", encoding="utf-8") as f:
        await f.write(json.dumps(payload))
