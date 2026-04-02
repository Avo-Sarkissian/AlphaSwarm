"""ReACT report engine and data types for post-simulation analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import structlog

if TYPE_CHECKING:
    from alphaswarm.ollama_client import OllamaClient

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
