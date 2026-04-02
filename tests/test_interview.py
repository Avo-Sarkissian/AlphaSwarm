"""Unit tests for interview data types, graph read method, and InterviewEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.errors import Neo4jConnectionError
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
