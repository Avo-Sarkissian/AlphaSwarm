"""Integration tests for Phase 25 wiring — CLI + HTML + system prompt + deterministic pre-seeding."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.report import (
    REACT_SYSTEM_PROMPT,
    ReportEngine,
    ToolObservation,
    build_react_system_prompt,
)


class TestReactSystemPromptBuilder:
    def test_default_excludes_portfolio(self) -> None:
        prompt = build_react_system_prompt()
        assert "portfolio_impact" not in prompt

    def test_default_excludes_portfolio_mandate(self) -> None:
        prompt = build_react_system_prompt()
        assert "PORTFOLIO REPORTING CONTRACT" not in prompt
        assert "MUST call it" not in prompt

    def test_include_portfolio_true_adds_tool_line(self) -> None:
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "portfolio_impact" in prompt
        assert "Map user's Schwab portfolio" in prompt

    def test_include_portfolio_true_contains_mandatory_clause(self) -> None:
        """REVIEWS HIGH concern: mandatory MUST-call instruction."""
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "PORTFOLIO REPORTING CONTRACT" in prompt
        assert "you MUST call it at least once" in prompt
        assert "MUST include a paragraph in your FINAL ANSWER" in prompt

    def test_include_portfolio_true_contains_context_awareness_clause(self) -> None:
        """REPLAN-7: explicit CONTEXT AWARENESS clause so the LLM knows the
        pre-seeded observation is already in its conversation context."""
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "CONTEXT AWARENESS" in prompt
        assert "You already have a portfolio_impact observation" in prompt

    def test_default_matches_module_constant(self) -> None:
        assert build_react_system_prompt() == REACT_SYSTEM_PROMPT

    def test_default_still_mentions_all_8_existing_tools(self) -> None:
        prompt = build_react_system_prompt()
        for tool in [
            "consensus_summary",
            "round_timeline",
            "bracket_narratives",
            "key_dissenters",
            "influence_leaders",
            "signal_flips",
            "entity_impact",
            "social_post_reach",
            "FINAL_ANSWER",
        ]:
            assert tool in prompt, f"Missing tool: {tool}"

    def test_portfolio_variant_still_mentions_all_existing_tools(self) -> None:
        prompt = build_react_system_prompt(include_portfolio=True)
        for tool in [
            "consensus_summary",
            "round_timeline",
            "bracket_narratives",
            "key_dissenters",
            "influence_leaders",
            "signal_flips",
            "entity_impact",
            "social_post_reach",
            "FINAL_ANSWER",
        ]:
            assert tool in prompt, f"Missing tool: {tool}"


class TestReportEnginePreSeededObservations:
    """Deterministic portfolio delivery: engine must include pre-seeded observations
    in its result even if the ReACT loop never calls the corresponding tool."""

    def _make_engine(
        self,
        *,
        tools: dict[str, Any] | None = None,
        pre_seeded: list[ToolObservation] | None = None,
        system_prompt: str | None = None,
    ) -> ReportEngine:
        fake_ollama = MagicMock()
        return ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools=tools or {},
            system_prompt=system_prompt,
            pre_seeded_observations=pre_seeded,
        )

    def test_default_pre_seeded_is_empty(self) -> None:
        engine = self._make_engine()
        assert engine._pre_seeded == []

    def test_pre_seeded_accepted(self) -> None:
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={"matched_tickers": [], "gap_tickers": [], "coverage_summary": {}},
        )
        engine = self._make_engine(pre_seeded=[obs])
        assert len(engine._pre_seeded) == 1
        assert engine._pre_seeded[0].tool_name == "portfolio_impact"

    @pytest.mark.asyncio
    async def test_run_returns_pre_seeded_even_when_llm_exits_immediately(
        self,
    ) -> None:
        """If the LLM returns FINAL_ANSWER without calling any tool, pre-seeded
        observations must still appear in the returned list."""
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 0,
                    "total_equity_holdings": 0,
                    "coverage_pct": 0.0,
                },
            },
        )

        # Real ollama_client mock — returns FINAL_ANSWER so run() exits on first iteration.
        fake_ollama = MagicMock()

        async def fake_chat(*, model, messages, think=False, **kwargs):
            response = MagicMock()
            response.message.content = "THOUGHT: done\nACTION: FINAL_ANSWER\nINPUT: {}"
            return response

        fake_ollama.chat = fake_chat

        engine = ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools={},
            pre_seeded_observations=[obs],
        )
        result = await engine.run("c1")
        assert len(result) == 1
        assert result[0].tool_name == "portfolio_impact"

    @pytest.mark.asyncio
    async def test_pre_seeded_observations_appear_in_llm_messages(
        self,
    ) -> None:
        """REPLAN-3/REPLAN-7: pre-seeded observations must be injected into the
        `messages` list (LLM conversation) BEFORE the first chat() call, so the
        model can see the pre-computed data in its context window."""
        import json as _json

        from alphaswarm import report as report_module

        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [{"ticker": "AAPL", "signal": "BUY"}],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )

        captured_messages: list[list[dict]] = []

        async def fake_chat(*, model, messages, think=False, **kwargs):
            # Snapshot the messages on each call so we can assert the very first
            # call already has the pre-seeded observation in the context.
            captured_messages.append([dict(m) for m in messages])
            response = MagicMock()
            response.message.content = "THOUGHT: done\nACTION: FINAL_ANSWER\nINPUT: {}"
            return response

        fake_ollama = MagicMock()
        fake_ollama.chat = fake_chat

        engine = ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools={},
            system_prompt=report_module.build_react_system_prompt(include_portfolio=True),
            pre_seeded_observations=[obs],
        )
        await engine.run("c1")

        assert len(captured_messages) >= 1, "ollama_client.chat was never called"
        first_call_messages = captured_messages[0]

        # The first message must be the system prompt
        assert first_call_messages[0]["role"] == "system"
        assert "portfolio_impact" in first_call_messages[0]["content"]
        assert "CONTEXT AWARENESS" in first_call_messages[0]["content"]

        # Find the injected OBSERVATION user message
        observation_messages = [
            m
            for m in first_call_messages
            if m["role"] == "user"
            and m["content"].startswith("OBSERVATION: portfolio_impact:")
        ]
        assert len(observation_messages) == 1, (
            "pre-seeded portfolio_impact observation must be injected as a "
            "user message BEFORE the first chat() call (REPLAN-3/REPLAN-7)"
        )
        # The JSON payload must round-trip the result dict
        payload = observation_messages[0]["content"].split(
            "OBSERVATION: portfolio_impact: ", 1
        )[1]
        parsed = _json.loads(payload)
        assert parsed["coverage_summary"]["covered"] == 1
        assert parsed["matched_tickers"][0]["ticker"] == "AAPL"
