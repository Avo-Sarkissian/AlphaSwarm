"""Unit tests for interview data types, graph read method, and InterviewEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.errors import Neo4jConnectionError
from alphaswarm.interview import InterviewContext
from alphaswarm.types import AgentPersona, BracketType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Mock AsyncDriver with session context manager support (same as test_graph.py)."""
    driver = MagicMock()
    driver.close = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session
    return driver


@pytest.fixture()
def sample_personas_for_interview() -> list[AgentPersona]:
    """2 AgentPersona objects with system_prompts ending in JSON_OUTPUT_INSTRUCTIONS."""
    return [
        AgentPersona(
            id="quants_01",
            name="Quants 1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt=f"You are a quantitative analyst in the Quants bracket.{JSON_OUTPUT_INSTRUCTIONS}",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01",
            name="Degens 1",
            bracket=BracketType.DEGENS,
            risk_profile=0.95,
            temperature=1.2,
            system_prompt=f"You are a high-risk speculator in the Degens bracket.{JSON_OUTPUT_INSTRUCTIONS}",
            influence_weight_base=0.3,
        ),
    ]


# ---------------------------------------------------------------------------
# Task 1: Data types and graph read tests
# ---------------------------------------------------------------------------


class TestRoundDecision:
    def test_frozen_dataclass_fields(self) -> None:
        from alphaswarm.interview import RoundDecision

        rd = RoundDecision(
            round_num=1, signal="buy", confidence=0.85, sentiment=0.6, rationale="Strong fundamentals"
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
            RoundDecision(round_num=1, signal="buy", confidence=0.8, sentiment=0.5, rationale="r1"),
            RoundDecision(round_num=2, signal="hold", confidence=0.6, sentiment=0.2, rationale="r2"),
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


class TestReadAgentInterviewContext:
    @pytest.mark.asyncio()
    async def test_returns_context_with_3_decisions(
        self, mock_driver: MagicMock, sample_personas_for_interview: list[AgentPersona],
    ) -> None:
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[
            {
                "agent_id": "quants_01", "name": "Quants 1", "bracket": "quants",
                "decision_narrative": "Went bullish then cautious.",
                "round_num": 1, "signal": "buy", "confidence": 0.85, "sentiment": 0.6, "rationale": "Strong data",
            },
            {
                "agent_id": "quants_01", "name": "Quants 1", "bracket": "quants",
                "decision_narrative": "Went bullish then cautious.",
                "round_num": 2, "signal": "hold", "confidence": 0.6, "sentiment": 0.2, "rationale": "Mixed signals",
            },
            {
                "agent_id": "quants_01", "name": "Quants 1", "bracket": "quants",
                "decision_narrative": "Went bullish then cautious.",
                "round_num": 3, "signal": "sell", "confidence": 0.7, "sentiment": -0.3, "rationale": "Risk off",
            },
        ])

        gsm = GraphStateManager(mock_driver, sample_personas_for_interview)
        ctx = await gsm.read_agent_interview_context("quants_01", "cycle-123")

        assert ctx.agent_id == "quants_01"
        assert ctx.agent_name == "Quants 1"
        assert ctx.bracket == "quants"
        assert len(ctx.decisions) == 3
        assert ctx.decisions[0].round_num == 1
        assert ctx.decisions[0].signal == "buy"
        assert ctx.decisions[2].round_num == 3
        assert ctx.decisions[2].signal == "sell"

    @pytest.mark.asyncio()
    async def test_handles_missing_decision_narrative(
        self, mock_driver: MagicMock, sample_personas_for_interview: list[AgentPersona],
    ) -> None:
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[
            {
                "agent_id": "quants_01", "name": "Quants 1", "bracket": "quants",
                "decision_narrative": None,
                "round_num": 1, "signal": "buy", "confidence": 0.8, "sentiment": 0.5, "rationale": "test",
            },
        ])

        gsm = GraphStateManager(mock_driver, sample_personas_for_interview)
        ctx = await gsm.read_agent_interview_context("quants_01", "cycle-123")

        assert ctx.decision_narrative == ""

    @pytest.mark.asyncio()
    async def test_strips_json_instructions_from_system_prompt(
        self, mock_driver: MagicMock, sample_personas_for_interview: list[AgentPersona],
    ) -> None:
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[
            {
                "agent_id": "quants_01", "name": "Quants 1", "bracket": "quants",
                "decision_narrative": "Narrative text.",
                "round_num": 1, "signal": "buy", "confidence": 0.8, "sentiment": 0.5, "rationale": "test",
            },
        ])

        gsm = GraphStateManager(mock_driver, sample_personas_for_interview)
        ctx = await gsm.read_agent_interview_context("quants_01", "cycle-123")

        assert JSON_OUTPUT_INSTRUCTIONS not in ctx.interview_system_prompt
        assert "quantitative analyst" in ctx.interview_system_prompt

    @pytest.mark.asyncio()
    async def test_raises_neo4j_connection_error_on_failure(
        self, mock_driver: MagicMock, sample_personas_for_interview: list[AgentPersona],
    ) -> None:
        from neo4j.exceptions import Neo4jError

        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(side_effect=Neo4jError("Connection lost"))

        gsm = GraphStateManager(mock_driver, sample_personas_for_interview)
        with pytest.raises(Neo4jConnectionError):
            await gsm.read_agent_interview_context("quants_01", "cycle-123")


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
            RoundDecision(round_num=1, signal="buy", confidence=0.85, sentiment=0.6, rationale="Strong fundamentals"),
            RoundDecision(round_num=2, signal="hold", confidence=0.6, sentiment=0.2, rationale="Mixed signals"),
            RoundDecision(round_num=3, signal="sell", confidence=0.7, sentiment=-0.3, rationale="Risk off mode"),
        ],
    )


def _make_mock_ollama_client(response_text: str = "I chose BUY because of strong fundamentals.") -> AsyncMock:
    """Create a mock OllamaClient with a chat() that returns a predictable response."""
    client = AsyncMock()
    mock_response = MagicMock()
    mock_response.message.content = response_text
    client.chat = AsyncMock(return_value=mock_response)
    return client


class TestInterviewEngineInit:
    def test_init_accepts_context_client_model(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client()
        engine = InterviewEngine(context=ctx, ollama_client=client, model="alphaswarm-worker")

        assert engine._context is ctx
        assert engine._client is client
        assert engine._model == "alphaswarm-worker"
        assert engine._history == []
        assert engine._summary is None

    def test_window_size_constant(self) -> None:
        from alphaswarm.interview import InterviewEngine

        assert InterviewEngine.WINDOW_SIZE == 10


class TestInterviewEngineAsk:
    @pytest.mark.asyncio()
    async def test_ask_appends_to_history_and_returns_response(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client("I bought because data was strong.")
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")

        result = await engine.ask("Why did you buy in round 1?")

        assert result == "I bought because data was strong."
        assert len(engine._history) == 2  # 1 user + 1 assistant
        assert engine._history[0] == {"role": "user", "content": "Why did you buy in round 1?"}
        assert engine._history[1] == {"role": "assistant", "content": "I bought because data was strong."}

    @pytest.mark.asyncio()
    async def test_ask_calls_ollama_chat_with_assembled_messages(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client()
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")

        await engine.ask("Hello")

        client.chat.assert_called_once()
        call_kwargs = client.chat.call_args
        messages = call_kwargs.kwargs["messages"]
        # System prompt is first, context block is second, then user message
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello"


class TestBuildMessages:
    def test_build_messages_without_summary(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client()
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")
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
        client = _make_mock_ollama_client()
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")
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
        client = _make_mock_ollama_client()
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")

        block = engine._build_context_block()
        assert "Narrative Summary" in block or "decision_narrative" in block.lower() or ctx.decision_narrative in block
        assert "Round 1" in block
        assert "Round 2" in block
        assert "Round 3" in block
        assert "buy" in block
        assert "Strong fundamentals" in block


class TestSlidingWindow:
    @pytest.mark.asyncio()
    async def test_sliding_window_trims_at_11_pairs(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client("Response")
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")

        for i in range(11):
            await engine.ask(f"Question {i}")

        # After 11 asks, should have 10 pairs (20 messages) and a summary
        assert len(engine._history) == 20
        assert engine._summary is not None
        assert len(engine._summary) > 0

    @pytest.mark.asyncio()
    async def test_summary_generation_calls_chat(self) -> None:
        from alphaswarm.interview import InterviewEngine

        ctx = _make_context()
        client = _make_mock_ollama_client("Response")
        engine = InterviewEngine(context=ctx, ollama_client=client, model="worker")

        for i in range(11):
            await engine.ask(f"Question {i}")

        # 11 ask calls + 1 summary generation = 12 chat calls
        assert client.chat.call_count == 12
