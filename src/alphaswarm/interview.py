"""Interview data types and conversation engine for post-simulation agent interviews."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="interview")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoundDecision:
    """Immutable record of an agent's decision in a single simulation round."""

    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str


@dataclass(frozen=True)
class InterviewContext:
    """Immutable context bundle for an agent interview session.

    Reconstructed from Neo4j at interview start. Contains persona identity,
    decision narrative summary, and per-round decision details.
    """

    agent_id: str
    agent_name: str
    bracket: str
    interview_system_prompt: str  # persona system_prompt with JSON instructions stripped
    decision_narrative: str  # pre-computed from Agent node (Phase 11)
    decisions: list[RoundDecision]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _strip_json_instructions(system_prompt: str) -> str:
    """Remove JSON_OUTPUT_INSTRUCTIONS from a persona system prompt.

    Interviews are conversational prose, not JSON-structured decisions (D-05).
    """
    return system_prompt.replace(JSON_OUTPUT_INSTRUCTIONS, "").rstrip()


# ---------------------------------------------------------------------------
# Interview Engine
# ---------------------------------------------------------------------------


class InterviewEngine:
    """Manages multi-turn agent interview conversation.

    Per D-08: 10-turn sliding window (10 user+agent pairs = 20 messages).
    Per D-09: Summary of dropped pairs prepended as system message.
    Per D-10: Summary generated via worker model (same model as interview).
    Per D-13: Uses OllamaClient.chat() directly (no governor).
    """

    WINDOW_SIZE = 10  # max user+agent message pairs

    def __init__(
        self,
        context: InterviewContext,
        ollama_client: OllamaClient,
        model: str,
    ) -> None:
        self._context = context
        self._client = ollama_client
        self._model = model
        self._history: list[dict[str, str]] = []
        self._summary: str | None = None
        self._log = structlog.get_logger(component="interview")

    def _build_system_prompt(self) -> str:
        """Return the agent's interview system prompt (JSON instructions already stripped)."""
        return self._context.interview_system_prompt

    def _build_context_block(self) -> str:
        """Build a formatted context block with decision narrative and per-round decisions."""
        lines = [
            "=== Your Simulation Context ===",
            "",
            "Narrative Summary:",
            self._context.decision_narrative,
            "",
            "Round-by-Round Decisions:",
        ]
        for d in self._context.decisions:
            lines.append(
                f"Round {d.round_num}: Signal={d.signal}, "
                f"Confidence={d.confidence}, Sentiment={d.sentiment}"
            )
            lines.append(f"Rationale: {d.rationale}")
        return "\n".join(lines)

    def _build_messages(self) -> list[dict[str, str]]:
        """Assemble the full message list for OllamaClient.chat().

        Structure:
        1. System prompt (persona identity)
        2. Context block (narrative + round decisions)
        3. Summary of earlier conversation (if any)
        4. Conversation history
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "system", "content": self._build_context_block()},
        ]
        if self._summary is not None:
            messages.append(
                {"role": "system", "content": f"[Earlier: {self._summary}]"}
            )
        messages.extend(self._history)
        return messages

    async def ask(self, user_message: str) -> str:
        """Send a user message and return the agent's response.

        Appends to history, calls LLM, trims window if needed.
        """
        self._history.append({"role": "user", "content": user_message})
        messages = self._build_messages()
        response = await self._client.chat(
            model=self._model, messages=messages, think=False,
        )
        assistant_content = response.message.content or ""
        self._history.append({"role": "assistant", "content": assistant_content})
        await self._trim_window()
        return assistant_content

    async def _trim_window(self) -> None:
        """Trim conversation history to WINDOW_SIZE pairs, summarizing dropped pairs."""
        pair_count = len(self._history) // 2
        if pair_count <= self.WINDOW_SIZE:
            return

        # Extract oldest pair
        dropped_user = self._history[0]
        dropped_assistant = self._history[1]

        # Remove oldest pair
        self._history = self._history[2:]

        # Generate summary of dropped pair via worker model
        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "In one sentence, summarize what the user asked and "
                    "what you said in the following exchange."
                ),
            },
            {"role": "user", "content": dropped_user["content"]},
            {"role": "assistant", "content": dropped_assistant["content"]},
            {"role": "user", "content": "Summarize the above exchange in one sentence."},
        ]
        summary_response = await self._client.chat(
            model=self._model, messages=summary_prompt, think=False,
        )
        new_summary = summary_response.message.content or ""

        # Merge with existing summary
        if self._summary is not None:
            self._summary = f"{self._summary} {new_summary}"
        else:
            self._summary = new_summary

        self._log.debug(
            "window_trimmed",
            pair_count=len(self._history) // 2,
            has_summary=True,
        )
