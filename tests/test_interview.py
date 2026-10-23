"""Unit tests for interview data types and InterviewEngine.

The graph read is covered against Neo4j in tests/neo4j/test_interview_context.py.
"""

from __future__ import annotations

import pytest

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.interview import InterviewContext

# ---------------------------------------------------------------------------
# Task 1: Data types tests
# ---------------------------------------------------------------------------


class TestRoundDecision:
    def test_frozen_dataclass_fields(self) -> None:
        from alphaswarm.interview import RoundDecision

        rd = RoundDecision(
            round_num=1,
            signal="buy",
            confidence=0.85,
            sentiment=0.6,
            rationale="Strong fundamentals",
        )
        assert rd.round_num == 1
        assert rd.signal == "buy"
        assert rd.confidence == 0.85
        assert rd.sentiment == 0.6
        assert rd.rationale == "Strong fundamentals"

    def test_frozen_immutability(self) -> None:
        from alphaswarm.interview import RoundDecision

        rd = RoundDecision(round_num=1, signal="buy", confidence=0.85, sentiment=0.6, rationale="x")
        with pytest.raises(AttributeError):
            rd.signal = "sell"  # type: ignore[misc]


class TestInterviewContext:
    def test_frozen_dataclass_fields(self) -> None:
        from alphaswarm.interview import InterviewContext, RoundDecision

        decisions = [
            RoundDecision(
                round_num=1,
                signal="buy",
                confidence=0.8,
                sentiment=0.5,
                rationale="r1",
            ),
            RoundDecision(
                round_num=2,
                signal="hold",
                confidence=0.6,
                sentiment=0.2,
                rationale="r2",
            ),
        ]
        ctx = InterviewContext(
            agent_id="quants_01",
            agent_name="Quants 1",
            bracket="quants",
            interview_system_prompt="You are a quantitative analyst.",
            decision_narrative="Agent went bullish then cautious.",
            decisions=decisions,
        )
        assert ctx.agent_id == "quants_01"
        assert ctx.agent_name == "Quants 1"
        assert ctx.bracket == "quants"
        assert ctx.interview_system_prompt == "You are a quantitative analyst."
        assert ctx.decision_narrative == "Agent went bullish then cautious."
        assert len(ctx.decisions) == 2

    def test_frozen_immutability(self) -> None:
        from alphaswarm.interview import InterviewContext

        ctx = InterviewContext(
            agent_id="quants_01",
            agent_name="Quants 1",
            bracket="quants",
            interview_system_prompt="test",
            decision_narrative="test",
            decisions=[],
        )
        with pytest.raises(AttributeError):
            ctx.agent_id = "degens_01"  # type: ignore[misc]


class TestStripJsonInstructions:
    def test_strips_json_instructions_from_prompt(self) -> None:
        from alphaswarm.interview import _strip_json_instructions

        prompt_with_json = f"You are a quant analyst.{JSON_OUTPUT_INSTRUCTIONS}"
        result = _strip_json_instructions(prompt_with_json)
        assert result == "You are a quant analyst."
        assert JSON_OUTPUT_INSTRUCTIONS not in result

    def test_no_json_instructions_returns_unchanged(self) -> None:
        from alphaswarm.interview import _strip_json_instructions

        prompt_without_json = "You are a quant analyst focused on data."
        result = _strip_json_instructions(prompt_without_json)
        assert result == prompt_without_json


# ---------------------------------------------------------------------------
# Task 2: InterviewEngine tests
# ---------------------------------------------------------------------------


def _make_context() -> InterviewContext:
    """Helper to create a sample InterviewContext for engine tests."""
    from alphaswarm.interview import InterviewContext, RoundDecision

    return InterviewContext(
        agent_id="quants_01",
        agent_name="Quants 1",
        bracket="quants",
        interview_system_prompt="You are a quantitative analyst in the Quants bracket.",
        decision_narrative="Agent went from BUY to HOLD to SELL across 3 rounds.",
        decisions=[
            RoundDecision(
                round_num=1,
                signal="buy",
                confidence=0.85,
                sentiment=0.6,
                rationale="Strong fundamentals",
            ),
            RoundDecision(
                round_num=2,
                signal="hold",
                confidence=0.6,
                sentiment=0.2,
                rationale="Mixed signals",
            ),
            RoundDecision(
                round_num=3,
                signal="sell",
                confidence=0.7,
                sentiment=-0.3,
                rationale="Risk off mode",
            ),
        ],
    )


def _make_fake_provider(
    response_text: str = "I chose BUY because of strong fundamentals.",
    count: int = 1,
):
    """Create a FakeInferenceProvider scripted with identical responses."""
    from alphaswarm.inference.types import InferenceResult, ProviderRole
    from tests.inference.fakes import FakeInferenceProvider

    scripted = [InferenceResult(content=response_text, model="test-worker") for _ in range(count)]
    return FakeInferenceProvider(role=ProviderRole.WORKER, model="test-worker", scripted=scripted)


class TestInterviewEngineInit:
    def test_init_accepts_context_and_provider(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider()
        engine = InterviewEngine(context=ctx, provider=provider)

        assert engine._context is ctx
        assert engine._provider is provider
        assert engine._history == []
        assert engine._summary is None

    def test_window_size_constant(self) -> None:
        from alphaswarm.interview import InterviewEngine

        assert InterviewEngine.WINDOW_SIZE == 10


class TestInterviewEngineAsk:
    async def test_ask_appends_to_history_and_returns_response(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider("I bought because data was strong.")
        engine = InterviewEngine(context=ctx, provider=provider)

        result = await engine.ask("Why did you buy in round 1?")

        assert result == "I bought because data was strong."
        assert len(engine._history) == 2  # 1 user + 1 assistant
        assert engine._history[0] == {"role": "user", "content": "Why did you buy in round 1?"}
        assert engine._history[1] == {
            "role": "assistant",
            "content": "I bought because data was strong.",
        }

    async def test_ask_calls_provider_chat_with_assembled_messages(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider()
        engine = InterviewEngine(context=ctx, provider=provider)

        await engine.ask("Hello")

        assert len(provider.calls) == 1
        messages = provider.calls[0]["messages"]
        # System prompt is first, context block is second, then user message
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello"


class TestBuildMessages:
    def test_build_messages_without_summary(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider()
        engine = InterviewEngine(context=ctx, provider=provider)
        engine._history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]

        messages = engine._build_messages()
        assert messages[0] == {"role": "system", "content": ctx.interview_system_prompt}
        assert messages[1]["role"] == "system"
        assert "Simulation Context" in messages[1]["content"]
        # No summary message
        assert messages[2] == {"role": "user", "content": "Hi"}
        assert messages[3] == {"role": "assistant", "content": "Hello"}

    def test_build_messages_with_summary(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider()
        engine = InterviewEngine(context=ctx, provider=provider)
        engine._summary = "User asked about round 1, agent explained buying rationale."
        engine._history = [
            {"role": "user", "content": "What about round 2?"},
            {"role": "assistant", "content": "I shifted to hold."},
        ]

        messages = engine._build_messages()
        assert messages[0]["role"] == "system"  # system prompt
        assert messages[1]["role"] == "system"  # context block
        assert messages[2]["role"] == "system"  # summary
        assert "[Earlier:" in messages[2]["content"]
        assert messages[3] == {"role": "user", "content": "What about round 2?"}

    def test_context_block_contains_decisions(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        provider = _make_fake_provider()
        engine = InterviewEngine(context=ctx, provider=provider)

        block = engine._build_context_block()
        assert "Narrative Summary" in block or "decision_narrative" in block.lower() or ctx.decision_narrative in block
        assert "Round 1" in block
        assert "Round 2" in block
        assert "Round 3" in block
        assert "buy" in block
        assert "Strong fundamentals" in block


class TestSlidingWindow:
    async def test_sliding_window_trims_at_11_pairs(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        # 11 ask responses + 1 summary generation = 12 total
        provider = _make_fake_provider("Response", count=12)
        engine = InterviewEngine(context=ctx, provider=provider)

        for i in range(11):
            await engine.ask(f"Question {i}")

        # After 11 asks, should have 10 pairs (20 messages) and a summary
        assert len(engine._history) == 20
        assert engine._summary is not None
        assert len(engine._summary) > 0

    async def test_summary_generation_calls_chat(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        # 11 ask responses + 1 summary generation = 12 total
        provider = _make_fake_provider("Response", count=12)
        engine = InterviewEngine(context=ctx, provider=provider)

        for i in range(11):
            await engine.ask(f"Question {i}")

        # 11 ask calls + 1 summary generation = 12 provider calls
        assert len(provider.calls) == 12


def test_context_block_omits_empty_narrative() -> None:
    from dataclasses import replace

    from alphaswarm.inference.types import ProviderRole
    from alphaswarm.interview import InterviewEngine
    from tests.inference.fakes import FakeInferenceProvider

    ctx = replace(_make_context(), decision_narrative="")
    engine = InterviewEngine(ctx, FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=[]))

    block = engine._build_context_block()

    assert "Narrative Summary" not in block
    assert "Round-by-Round Decisions:" in block


def test_round_decision_cited_agents_defaults_to_empty() -> None:
    from alphaswarm.interview import RoundDecision

    decision = RoundDecision(round_num=1, signal="buy", confidence=0.5, sentiment=0.0, rationale="r")

    assert decision.cited_agents == ()
