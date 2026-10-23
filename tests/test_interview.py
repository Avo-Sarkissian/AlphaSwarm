"""Unit tests for interview data types and InterviewEngine.

The graph read is covered against Neo4j in tests/neo4j/test_interview_context.py.
"""

from __future__ import annotations

import pytest

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.interview import InterviewContext

# ---------------------------------------------------------------------------
# Data types tests
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
# InterviewEngine tests
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

        assert InterviewEngine.WINDOW_SIZE == 12
        assert InterviewEngine.TRIM_BLOCK_PAIRS == 6


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
    async def test_sliding_window_trims_a_block_at_13_pairs(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        # 13 ask responses + 1 summary = 14
        provider = _make_fake_provider("Response", count=14)
        engine = InterviewEngine(context=ctx, provider=provider)

        for i in range(13):
            await engine.ask(f"Question {i}")

        # After 13 asks the oldest 6 pairs are summarized: 7 pairs (14 messages) remain
        assert len(engine._history) == 14
        assert engine._summary is not None
        assert len(engine._summary) > 0

    async def test_summary_generation_calls_chat(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        # 13 ask responses + 1 summary = 14
        provider = _make_fake_provider("Response", count=14)
        engine = InterviewEngine(context=ctx, provider=provider)

        for i in range(13):
            await engine.ask(f"Question {i}")

        # 13 ask responses + 1 summary = 14
        assert len(provider.calls) == 14


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


class TestLazyNarrative:
    """Narrative generated once, on the first interview of (cycle, agent)."""

    class _Store:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str, str]] = []

        async def write_decision_narrative(
            self,
            cycle_id: str,
            agent_id: str,
            narrative: str,
        ) -> None:
            self.writes.append((cycle_id, agent_id, narrative))

    @staticmethod
    def _context(narrative: str = "") -> InterviewContext:
        from alphaswarm.interview import RoundDecision

        return InterviewContext(
            agent_id="quants_01",
            agent_name="Quants 1",
            bracket="quants",
            interview_system_prompt="You are a quantitative analyst.",
            decision_narrative=narrative,
            decisions=[
                RoundDecision(round_num=1, signal="buy", confidence=0.8, sentiment=0.5, rationale="r1"),
                RoundDecision(
                    round_num=2,
                    signal="sell",
                    confidence=0.6,
                    sentiment=-0.2,
                    rationale="r2",
                    cited_agents=("sell_side_01",),
                ),
            ],
        )

    async def test_generates_once_and_stores_on_first_interview(self) -> None:
        from alphaswarm.inference.types import InferenceResult, ProviderRole
        from alphaswarm.interview import ensure_decision_narrative
        from tests.inference.fakes import FakeInferenceProvider

        store = self._Store()
        provider = FakeInferenceProvider(
            ProviderRole.WORKER,
            "w",
            scripted=[InferenceResult(content="  Bought, then sold.  ", model="w")],
        )

        ctx = await ensure_decision_narrative(store, provider, self._context(), cycle_id="c1")

        assert ctx.decision_narrative == "Bought, then sold."
        assert store.writes == [("c1", "quants_01", "Bought, then sold.")]
        assert len(provider.calls) == 1

    async def test_existing_narrative_is_reused_without_inference(self) -> None:
        from alphaswarm.inference.types import ProviderRole
        from alphaswarm.interview import ensure_decision_narrative
        from tests.inference.fakes import FakeInferenceProvider

        store = self._Store()
        provider = FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=[])

        ctx = await ensure_decision_narrative(
            store,
            provider,
            self._context("Stored."),
            cycle_id="c1",
        )

        assert ctx.decision_narrative == "Stored."
        assert provider.calls == [] and store.writes == []

    async def test_agent_without_decisions_gets_no_narrative(self) -> None:
        from dataclasses import replace

        from alphaswarm.inference.types import ProviderRole
        from alphaswarm.interview import ensure_decision_narrative
        from tests.inference.fakes import FakeInferenceProvider

        store = self._Store()
        provider = FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=[])
        empty = replace(self._context(), decisions=[])

        assert await ensure_decision_narrative(store, provider, empty, cycle_id="c1") is empty
        assert provider.calls == [] and store.writes == []

    async def test_inference_failure_keeps_interview_working(self) -> None:
        from alphaswarm.errors import InferenceError
        from alphaswarm.inference.types import InferenceResult, ProviderRole
        from alphaswarm.interview import ensure_decision_narrative
        from tests.inference.fakes import FakeInferenceProvider

        def _boom(**_: object) -> InferenceResult:
            raise InferenceError("worker timed out", provider="ollama", model="w")

        store = self._Store()
        provider = FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=_boom)

        ctx = await ensure_decision_narrative(store, provider, self._context(), cycle_id="c1")

        assert ctx.decision_narrative == ""
        assert store.writes == []

    async def test_hard_stop_errors_propagate(self) -> None:
        from decimal import Decimal

        from alphaswarm.errors import BudgetExceededError
        from alphaswarm.inference.types import InferenceResult, ProviderRole
        from alphaswarm.interview import ensure_decision_narrative
        from tests.inference.fakes import FakeInferenceProvider

        def _over_budget(**_: object) -> InferenceResult:
            raise BudgetExceededError(Decimal("1.00"), Decimal("0.50"))

        provider = FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=_over_budget)

        with pytest.raises(BudgetExceededError):
            await ensure_decision_narrative(self._Store(), provider, self._context(), cycle_id="c1")

    def test_prompt_uses_the_rounds_that_ran(self) -> None:
        from alphaswarm.interview import NARRATIVE_SYSTEM_PROMPT, build_narrative_messages

        messages = build_narrative_messages(self._context())

        assert messages[0] == {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT}
        user = messages[1]["content"]
        assert "this agent's 2-round decision arc" in user
        assert "Round 2: SELL (confidence: 0.60, sentiment: -0.20) flip: buy_to_sell" in user
        assert "  Cited: sell_side_01" in user
