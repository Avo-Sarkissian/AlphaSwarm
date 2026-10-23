"""ReACT report engine and data types for post-simulation analysis."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from alphaswarm.errors import AlphaSwarmError
from alphaswarm.fsutil import atomic_write_text

if TYPE_CHECKING:
    from alphaswarm.graph import (
        BracketNarrativeRow,
        ConsensusSummaryRow,
        EntityImpactRow,
        GraphStateManager,
        InfluenceLeaderRow,
        KeyDissenterRow,
        RoundTimelineRow,
        ShockImpactRow,
        SignalFlipRow,
    )
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.inference.types import InferenceMessage

log = structlog.get_logger(component="report")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10

REACT_SYSTEM_PROMPT = """\
You are a post-simulation market analysis agent. Your task is to query the \
simulation graph and produce a comprehensive structured analysis report.

Available tools:
- bracket_summary: Get the global BUY/SELL/HOLD/PARSE_ERROR breakdown for the final round
- round_timeline: Get the signal distribution for every round that ran
- bracket_narratives: Get the per-bracket stance summary for the final round
- key_dissenters: Find agents whose final-round signal diverges from their bracket majority
- influence_leaders: Get the most-cited agents in the final round, with influence share
- signal_flip_analysis: Get agents who changed position between rounds
- entity_impact: Get per-entity sentiment aggregation for the final round
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
        provider: InferenceProvider,
        tools: dict[str, Callable],  # type: ignore[type-arg]
        *,
        pre_seeded_observations: list[ToolObservation] | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._pre_seeded: list[ToolObservation] = list(pre_seeded_observations or [])
        self._log = structlog.get_logger(component="report")

    async def run(self, cycle_id: str) -> list[ToolObservation]:
        """Execute the ReACT loop and return accumulated tool observations.

        Args:
            cycle_id: The simulation cycle ID to generate a report for.

        Returns:
            List of ToolObservation records from successful tool dispatches.
        """
        observations: list[ToolObservation] = list(self._pre_seeded)
        seen_calls: set[tuple[str, str]] = set()

        messages: list[InferenceMessage] = [
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
            result = await self._provider.chat(messages)
            content = result.content or ""
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
                    "react_duplicate_call",
                    action=action,
                    iteration=iteration,
                )
                break
            seen_calls.add(call_key)

            # Dispatch tool
            tool_fn = self._tools.get(action)
            if tool_fn is None:
                observation_text = f"ERROR: Unknown tool '{action}'"
                messages.append({"role": "user", "content": f"OBSERVATION: {observation_text}"})
                continue

            # Malformed INPUT (partially captured multiline JSON, a JSON list,
            # unexpected kwargs) must not kill the whole report — feed an
            # ERROR observation back into the loop, mirroring the
            # unknown-tool branch above.
            try:
                parsed_input: dict[str, object] = json.loads(input_json or "{}")
                result = await tool_fn(**parsed_input)
            except (json.JSONDecodeError, TypeError) as exc:
                observation_text = f"ERROR: invalid INPUT for tool '{action}': {exc}"
                self._log.warning(
                    "react_tool_input_error",
                    action=action,
                    iteration=iteration,
                    error=str(exc),
                )
                messages.append({"role": "user", "content": f"OBSERVATION: {observation_text}"})
                continue
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

_WHITESPACE_RE = re.compile(r"\s+")


def md_cell(value: object) -> str:
    """Make free text safe for one markdown table cell.

    Collapses every whitespace run (including newlines) to one space and
    escapes backslashes and pipes, so a shock text or entity name can never
    split a row. None renders as an empty string.
    """
    if value is None:
        return ""
    text = _WHITESPACE_RE.sub(" ", str(value)).strip()
    return text.replace("\\", "\\\\").replace("|", "\\|")


def num(value: object, digits: int = 2) -> str:
    """Fixed-digit number for report cells; None renders as an em dash."""
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"num filter expects a number, got {type(value).__name__}")
    return f"{float(value):.{digits}f}"


class ReportDataError(AlphaSwarmError):
    """The cycle has nothing to report on (no decisions were persisted)."""


@dataclass(frozen=True)
class ReportData:
    """Everything a report renders, read once with the cycle id bound server-side."""

    cycle_id: str
    final_round: int
    seed_rumor: str
    consensus: ConsensusSummaryRow
    timeline: list[RoundTimelineRow]
    brackets: list[BracketNarrativeRow]
    dissenters: list[KeyDissenterRow]
    influence: list[InfluenceLeaderRow]
    flips: list[SignalFlipRow]
    entities: list[EntityImpactRow]
    shock: ShockImpactRow | None
    generated_at: datetime


async def resolve_final_round(gm: GraphStateManager, cycle_id: str) -> int:
    """Last round that has decisions: 2 or 3 (docs/DECISIONS.md#adr-num-rounds)."""
    timeline = await gm.read_round_timeline(cycle_id)
    rounds = [int(row["round_num"]) for row in timeline]
    if not rounds:
        raise ReportDataError(f"Cycle {cycle_id} has no decisions to report on")
    return max(rounds)


async def collect_report_data(
    gm: GraphStateManager,
    cycle_id: str,
    final_round: int,
) -> ReportData:
    """Run every report read concurrently for *cycle_id*.

    The model never chooses a query or a cycle id. ``asyncio.gather`` is enough
    here: the reads are independent and read-only, and the first failure
    propagates unwrapped to the job (docs/DECISIONS.md#adr-report-react). The
    nine reads are split into two inner gathers (both scheduled immediately, so
    all nine run concurrently) because typeshed types ``gather`` precisely only up
    to six awaitables.
    """
    tables = asyncio.gather(
        gm.read_consensus_summary(cycle_id),
        gm.read_round_timeline(cycle_id),
        gm.read_bracket_narratives(cycle_id),
        gm.read_key_dissenters(cycle_id),
        gm.read_influence_leaders(cycle_id),
        gm.read_signal_flips(cycle_id),
    )
    extras = asyncio.gather(
        gm.read_entity_impact(cycle_id),
        gm.read_shock_event(cycle_id),
        gm.read_cycle_seed(cycle_id),
    )
    (consensus, timeline, brackets, dissenters, influence, flips), (entities, shock_event, seed) = await asyncio.gather(
        tables, extras
    )
    shock = await gm.read_shock_impact(cycle_id) if shock_event is not None else None
    return ReportData(
        cycle_id=cycle_id,
        final_round=final_round,
        seed_rumor=seed or "",
        consensus=consensus,
        timeline=list(timeline),
        brackets=list(brackets),
        dissenters=list(dissenters),
        influence=list(influence),
        flips=list(flips),
        entities=list(entities),
        shock=shock,
        generated_at=datetime.now(UTC),
    )


#: Section order (docs/DECISIONS.md#p15-d-07): ReportData attribute -> template.
SECTION_TEMPLATES: Final[tuple[tuple[str, str], ...]] = (
    ("consensus", "01_consensus_summary.j2"),
    ("timeline", "02_round_timeline.j2"),
    ("brackets", "03_bracket_narratives.j2"),
    ("dissenters", "04_key_dissenters.j2"),
    ("influence", "05_influence_leaders.j2"),
    ("flips", "06_signal_flip_analysis.j2"),
    ("entities", "07_entity_impact.j2"),
    ("shock", "11_shock_impact.j2"),
)

NARRATIVE_UNAVAILABLE: Final = (
    "_Narrative unavailable: the orchestrator's reply could not be parsed. Every table below is complete._"
)
_NARRATIVE_LIMITS: Final[dict[str, int]] = {"moments": 6, "dissent": 5, "followups": 5}
_ITEM_MAX_CHARS: Final = 400
_SUMMARY_MAX_CHARS: Final = 1200
# Leading list/heading/quote markup followed by whitespace ("## ", "- ", "> "). The
# whitespace is required so a signed number ("-12% guidance") keeps its sign.
_LEADING_MARKUP_RE: Final = re.compile(r"^(?:[#>*\-+]+\s+)+")
_SPACES_RE: Final = re.compile(r"\s+")


def _clean_text(value: str, max_chars: int) -> str:
    """One line: whitespace collapsed, leading markdown stripped, length capped."""
    text = _LEADING_MARKUP_RE.sub("", _SPACES_RE.sub(" ", value).strip())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


class ReportNarrativeLLMOutput(BaseModel):
    """The single orchestrator reply a report needs.

    Lenient so formatting slips never cost a retry: extra keys ignored, text
    collapsed to one line, lists capped instead of rejected. Only an empty
    summary fails validation (docs/DECISIONS.md#adr-structured-output).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    summary: str = Field(min_length=1)
    moments: list[str] = Field(default_factory=list)
    dissent: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _clean_summary(cls, value: object) -> object:
        return _clean_text(value, _SUMMARY_MAX_CHARS) if isinstance(value, str) else value

    @field_validator("moments", "dissent", "followups", mode="before")
    @classmethod
    def _clean_items(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return []
        items = [value] if isinstance(value, str) else value
        if not isinstance(items, list):
            return items
        cleaned = [_clean_text(item, _ITEM_MAX_CHARS) for item in items if isinstance(item, str)]
        limit = _NARRATIVE_LIMITS[info.field_name or ""]
        return [item for item in cleaned if item][:limit]


@dataclass(frozen=True)
class ReportSections:
    """Structured report view served next to the markdown for the web UI."""

    summary: str
    convergence: list[RoundTimelineRow]
    influence: list[InfluenceLeaderRow]
    moments: list[str]
    dissent: list[str]
    followups: list[str]


def render_report(data: ReportData, narrative: ReportNarrativeLLMOutput | None) -> str:
    """Markdown report: header, executive summary, the section tables, narrative lists."""
    assembler = ReportAssembler()
    parts = [
        "# Post-Simulation Analysis Report\n\n"
        f"**Cycle:** {data.cycle_id}\n"
        f"**Generated:** {data.generated_at.isoformat()}\n"
        f"**Rounds:** {data.final_round}\n"
        f"**Rumor:** {md_cell(data.seed_rumor) or '—'}\n\n"
        "---\n",
        "## Executive Summary\n\n" + (narrative.summary if narrative is not None else NARRATIVE_UNAVAILABLE) + "\n",
    ]
    for attribute, template in SECTION_TEMPLATES:
        rows = getattr(data, attribute)
        if attribute == "shock" and rows is None:
            continue
        rendered = assembler.render_section(template, data=rows, cycle_id=data.cycle_id)
        parts.append(rendered.rstrip() + "\n")
    if narrative is not None:
        for heading, items in (
            ("Key Moments", narrative.moments),
            ("Dissent", narrative.dissent),
            ("Follow-ups", narrative.followups),
        ):
            if items:
                parts.append(f"## {heading}\n\n" + "\n".join(f"- {item}" for item in items) + "\n")
    return "\n".join(parts)


def build_sections(data: ReportData, narrative: ReportNarrativeLLMOutput | None) -> ReportSections:
    """The structured view the web UI charts: convergence and influence rows plus the narrative."""
    return ReportSections(
        summary=narrative.summary if narrative is not None else "",
        convergence=list(data.timeline),
        influence=list(data.influence),
        moments=list(narrative.moments) if narrative is not None else [],
        dissent=list(narrative.dissent) if narrative is not None else [],
        followups=list(narrative.followups) if narrative is not None else [],
    )


TOOL_TO_TEMPLATE: dict[str, str] = {
    "bracket_summary": "01_consensus_summary.j2",
    "round_timeline": "02_round_timeline.j2",
    "bracket_narratives": "03_bracket_narratives.j2",
    "key_dissenters": "04_key_dissenters.j2",
    "influence_leaders": "05_influence_leaders.j2",
    "signal_flip_analysis": "06_signal_flip_analysis.j2",
    "entity_impact": "07_entity_impact.j2",
    "shock_impact": "11_shock_impact.j2",
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
    "shock_impact",
]


class ReportAssembler:
    """Jinja2-based assembler for post-simulation analysis reports.

    Renders each section from a ToolObservation list and concatenates them
    into a single markdown document in canonical SECTION_ORDER.
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,  # markdown output, not HTML
            trim_blocks=True,
            lstrip_blocks=True,
            # A template that reads a key the row does not have must fail the
            # report instead of rendering a blank column
            # (docs/DECISIONS.md#adr-report-react).
            undefined=StrictUndefined,
        )
        self._env.filters["md_cell"] = md_cell
        self._env.filters["num"] = num

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

        now_iso = datetime.now(tz=UTC).isoformat()
        header = f"# Post-Simulation Analysis Report\n\n**Cycle:** {cycle_id}\n**Generated:** {now_iso}\n\n---\n\n"

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


async def write_report(path: Path, content: str) -> None:
    """Write the report markdown atomically (temp file + fsync + os.replace), off the loop.

    Creates the parent directory. Readers see the old file or the complete new
    one, never a truncated file (docs/DECISIONS.md#adr-background-tasks).
    """
    await asyncio.to_thread(atomic_write_text, path, content)
