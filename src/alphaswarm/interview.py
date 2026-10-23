"""Interview data types and conversation engine for post-simulation agent interviews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from alphaswarm.batch_dispatcher import HARD_STOP_ERRORS
from alphaswarm.episodes import compute_flip_type
from alphaswarm.errors import AgentNotFoundError
from alphaswarm.inference.caps import (
    DECISION_NARRATIVE_MAX_TOKENS,
    INTERVIEW_REPLY_MAX_TOKENS,
    INTERVIEW_SUMMARY_MAX_TOKENS,
)
from alphaswarm.inference.types import InferenceMessage
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.graph.rows import AgentDecisionRow, AgentInterviewRows
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.types import AgentPersona

log = structlog.get_logger(component="interview")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


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
    decisions: list[AgentDecisionRow]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _strip_json_instructions(system_prompt: str) -> str:
    """Remove JSON_OUTPUT_INSTRUCTIONS from a persona system prompt.

    Interviews are conversational prose, not JSON-structured decisions (D-05).
    """
    return system_prompt.replace(JSON_OUTPUT_INSTRUCTIONS, "").rstrip()


def interview_persona(rows: AgentInterviewRows, cycle_id: str) -> AgentPersona:
    """The agent's persona as it ran in this cycle: config plus the cycle's
    stored modifiers (docs/DECISIONS.md#p14-d-06).

    Raises:
        AgentNotFoundError: the agent is not in the current roster.
    """
    personas = generate_personas(load_bracket_configs(), modifiers=rows["modifiers"])
    persona = next((p for p in personas if p.id == rows["agent_id"]), None)
    if persona is None:
        raise AgentNotFoundError(rows["agent_id"], cycle_id)
    return persona


def build_interview_context(rows: AgentInterviewRows, persona: AgentPersona) -> InterviewContext:
    """Interview context from graph rows; JSON instructions stripped (docs/DECISIONS.md#p14-d-05)."""
    return InterviewContext(
        agent_id=rows["agent_id"],
        agent_name=rows["name"],
        bracket=rows["bracket"],
        interview_system_prompt=_strip_json_instructions(persona.system_prompt),
        decision_narrative=rows["narrative"],
        decisions=list(rows["decisions"]),
    )


async def load_interview_context(graph: GraphStateManager, agent_id: str, cycle_id: str) -> InterviewContext:
    """Read the agent's rows for the cycle and build its interview context."""
    rows = await graph.read_agent_interview_rows(agent_id, cycle_id)
    return build_interview_context(rows, interview_persona(rows, cycle_id))


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
        current = _signal_or_none(decision["signal"])
        flip = compute_flip_type(previous, current).value if current is not None else "none"
        lines.append(
            f"Round {decision['round_num']}: {decision['signal'].upper()} "
            f"(confidence: {decision['confidence']:.2f}, sentiment: {decision['sentiment']:.2f}) "
            f"flip: {flip}"
        )
        if decision["cited_agents"]:
            lines.append(f"  Cited: {', '.join(decision['cited_agents'])}")
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
        result = await provider.chat(build_narrative_messages(context), max_tokens=DECISION_NARRATIVE_MAX_TOKENS)
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
    """Multi-turn agent interview conversation.

    History holds complete user/assistant pairs only: a turn is committed after
    the provider answers, so a failed call never leaves an orphaned user message.
    Once more than WINDOW_SIZE pairs exist, the oldest TRIM_BLOCK_PAIRS pairs are
    summarized in one worker call and prepended as "[Earlier: ...]"
    (docs/DECISIONS.md#p14-d-08, #p14-d-09, #p14-d-10). No governor
    (docs/DECISIONS.md#p14-d-13).
    """

    WINDOW_SIZE = 12  # pairs kept before a block trim
    TRIM_BLOCK_PAIRS = 6  # pairs folded into the summary per trim
    SUMMARY_MAX_CHARS = 1500  # cap on the merged summary (a few two-sentence block summaries)

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
            lines.append(
                f"Round {d['round_num']}: Signal={d['signal']}, "
                f"Confidence={d['confidence']}, Sentiment={d['sentiment']}"
            )
            lines.append(f"Rationale: {d['rationale']}")
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
        """Send *user_message* and return the agent's answer.

        The user turn and the answer are appended together after the provider
        succeeds. A failed summary call does not fail a turn whose answer exists:
        the trim is retried on the next turn (hard-stop errors still propagate).
        """
        user_turn: InferenceMessage = {"role": "user", "content": user_message}
        result = await self._provider.chat([*self._build_messages(), user_turn], max_tokens=INTERVIEW_REPLY_MAX_TOKENS)
        assistant_content = result.content or ""
        self._history.extend([user_turn, {"role": "assistant", "content": assistant_content}])
        try:
            await self._trim_window()
        except HARD_STOP_ERRORS:
            raise
        except Exception:  # the answer exists; the trim retries next turn
            self._log.warning(
                "interview_trim_failed",
                pair_count=len(self._history) // 2,
                exc_info=True,
            )
        return assistant_content

    async def _trim_window(self) -> None:
        """Fold the oldest TRIM_BLOCK_PAIRS pairs into the summary once over WINDOW_SIZE."""
        if len(self._history) // 2 <= self.WINDOW_SIZE:
            return
        block = self._history[: self.TRIM_BLOCK_PAIRS * 2]
        summary_prompt: list[InferenceMessage] = [
            {
                "role": "system",
                "content": (
                    "In at most two sentences, summarize what the user asked and what "
                    "you said in the following exchanges."
                ),
            },
            *block,
            {"role": "user", "content": "Summarize the exchanges above in at most two sentences."},
        ]
        summary_result = await self._provider.chat(summary_prompt, max_tokens=INTERVIEW_SUMMARY_MAX_TOKENS)
        new_summary = summary_result.content or ""
        # Cap the merged summary so it cannot grow without bound; keep the newest tail.
        merged = f"{self._summary} {new_summary}" if self._summary is not None else new_summary
        if len(merged) > self.SUMMARY_MAX_CHARS:
            merged = merged[-self.SUMMARY_MAX_CHARS :].lstrip()
        # Commit both mutations only after the summary succeeded
        # (docs/DECISIONS.md#f-15).
        self._summary = merged
        self._history = self._history[self.TRIM_BLOCK_PAIRS * 2 :]
        self._log.debug("window_trimmed", pair_count=len(self._history) // 2, has_summary=True)
