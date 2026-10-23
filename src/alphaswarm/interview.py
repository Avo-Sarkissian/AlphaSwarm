"""Interview data types and conversation engine for post-simulation agent interviews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from alphaswarm.batch_dispatcher import HARD_STOP_ERRORS
from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.episodes import compute_flip_type
from alphaswarm.inference.types import InferenceMessage
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider

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
    cited_agents: tuple[str, ...] = ()


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
    decision_narrative: str  # this cycle's final-round Decision.narrative, "" when absent
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
# Lazy decision narratives (docs/DECISIONS.md#p11-d-11)
# ---------------------------------------------------------------------------

NARRATIVE_SYSTEM_PROMPT: Final = (
    "You are a concise financial analyst narrator. Summarize agent decision arcs in 2-3 sentences."
)


class NarrativeStore(Protocol):
    """Persistence seam for lazy narratives; GraphStateManager satisfies it."""

    async def write_decision_narrative(self, cycle_id: str, agent_id: str, narrative: str) -> None: ...


def _signal_or_none(value: str) -> SignalType | None:
    try:
        return SignalType(value.lower())
    except ValueError:
        return None


def build_narrative_messages(context: InterviewContext) -> list[InferenceMessage]:
    """Prompt for one agent's decision arc, sized to the rounds that actually ran."""
    lines = [f"Agent: {context.agent_name} ({context.bracket})", ""]
    previous: SignalType | None = None
    for decision in context.decisions:
        current = _signal_or_none(decision.signal)
        flip = compute_flip_type(previous, current).value if current is not None else "none"
        lines.append(
            f"Round {decision.round_num}: {decision.signal.upper()} "
            f"(confidence: {decision.confidence:.2f}, sentiment: {decision.sentiment:.2f}) "
            f"flip: {flip}"
        )
        if decision.cited_agents:
            lines.append(f"  Cited: {', '.join(decision.cited_agents)}")
        previous = current
    prompt = (
        f"Summarize this agent's {len(context.decisions)}-round decision arc in 2-3 sentences. "
        "Note any signal changes and key influences. Be concise.\n\n" + "\n".join(lines)
    )
    return [
        {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


async def ensure_decision_narrative(
    store: NarrativeStore,
    provider: InferenceProvider,
    context: InterviewContext,
    *,
    cycle_id: str,
) -> InterviewContext:
    """Return the context with a narrative, generating and storing it once.

    Reuses a stored narrative; skips agents without decisions. Hard-stop errors
    (budget, auth, governor crisis) propagate; any other inference failure is
    logged and the interview continues without a narrative.
    """
    if context.decision_narrative or not context.decisions:
        return context
    try:
        result = await provider.chat(build_narrative_messages(context))
    except HARD_STOP_ERRORS:
        raise
    except Exception:  # an interview still works without a narrative
        log.warning(
            "narrative_generation_failed",
            cycle_id=cycle_id,
            agent_id=context.agent_id,
            exc_info=True,
        )
        return context
    narrative = (result.content or "").strip()
    if not narrative:
        log.warning("narrative_generation_empty", cycle_id=cycle_id, agent_id=context.agent_id)
        return context
    await store.write_decision_narrative(cycle_id, context.agent_id, narrative)
    log.info(
        "narrative_generated",
        cycle_id=cycle_id,
        agent_id=context.agent_id,
        chars=len(narrative),
    )
    return replace(context, decision_narrative=narrative)


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
    SUMMARY_MAX_CHARS = 1500  # cap on merged summary (~10 one-sentence summaries)

    def __init__(
        self,
        context: InterviewContext,
        provider: InferenceProvider,
    ) -> None:
        self._context = context
        self._provider = provider
        self._history: list[InferenceMessage] = []
        self._summary: str | None = None
        self._log = structlog.get_logger(component="interview")

    def _build_system_prompt(self) -> str:
        """Return the agent's interview system prompt (JSON instructions already stripped)."""
        return self._context.interview_system_prompt

    def _build_context_block(self) -> str:
        """Context block: narrative (when one exists) plus per-round decisions."""
        lines = ["=== Your Simulation Context ===", ""]
        if self._context.decision_narrative:
            lines += ["Narrative Summary:", self._context.decision_narrative, ""]
        lines.append("Round-by-Round Decisions:")
        for d in self._context.decisions:
            lines.append(f"Round {d.round_num}: Signal={d.signal}, Confidence={d.confidence}, Sentiment={d.sentiment}")
            lines.append(f"Rationale: {d.rationale}")
        return "\n".join(lines)

    def _build_messages(self) -> list[InferenceMessage]:
        """Assemble the full message list for provider.chat().

        Structure:
        1. System prompt (persona identity)
        2. Context block (narrative + round decisions)
        3. Summary of earlier conversation (if any)
        4. Conversation history
        """
        messages: list[InferenceMessage] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "system", "content": self._build_context_block()},
        ]
        if self._summary is not None:
            messages.append({"role": "system", "content": f"[Earlier: {self._summary}]"})
        messages.extend(self._history)
        return messages

    async def ask(self, user_message: str) -> str:
        """Send a user message and return the agent's response.

        Appends to history, calls LLM, trims window if needed.
        """
        self._history.append({"role": "user", "content": user_message})
        messages = self._build_messages()
        result = await self._provider.chat(messages)
        assistant_content = result.content or ""
        self._history.append({"role": "assistant", "content": assistant_content})
        await self._trim_window()
        return assistant_content

    async def _trim_window(self) -> None:
        """Trim conversation history to WINDOW_SIZE pairs, summarizing dropped pairs."""
        pair_count = len(self._history) // 2
        if pair_count <= self.WINDOW_SIZE:
            return

        # Read (do NOT yet remove) the oldest pair. We must not mutate
        # self._history until the summary chat succeeds: if it raises (transient
        # backend error, timeout, cloud rate-limit), an early splice would
        # permanently discard a turn of context AND fail the current ask() whose
        # answer was already produced (F-15). Trimming simply retries next turn.
        dropped_user = self._history[0]
        dropped_assistant = self._history[1]

        # Generate summary of dropped pair via worker model
        summary_prompt: list[InferenceMessage] = [
            {
                "role": "system",
                "content": (
                    "In one sentence, summarize what the user asked and what you said in the following exchange."
                ),
            },
            {"role": "user", "content": dropped_user["content"]},
            {"role": "assistant", "content": dropped_assistant["content"]},
            {"role": "user", "content": "Summarize the above exchange in one sentence."},
        ]
        summary_result = await self._provider.chat(summary_prompt)
        new_summary = summary_result.content or ""

        # Merge with existing summary, capped at SUMMARY_MAX_CHARS so the
        # summary cannot grow unboundedly (one sentence per trimmed pair,
        # forever). Keep the most recent tail when over budget.
        merged = f"{self._summary} {new_summary}" if self._summary is not None else new_summary
        if len(merged) > self.SUMMARY_MAX_CHARS:
            merged = merged[-self.SUMMARY_MAX_CHARS :].lstrip()

        # Commit both mutations only after the summary succeeded.
        self._summary = merged
        self._history = self._history[2:]

        self._log.debug(
            "window_trimmed",
            pair_count=len(self._history) // 2,
            has_summary=True,
        )
