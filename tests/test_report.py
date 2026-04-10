"""Unit tests for ReportEngine, parser, and graph query tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.report import MAX_ITERATIONS, _parse_action_input


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_ollama_response(content: str) -> MagicMock:
    """Create a mock OllamaClient response with the given message content."""
    mock_resp = MagicMock()
    mock_resp.message.content = content
    return mock_resp


# ---------------------------------------------------------------------------
# Task 15-01-01: TestParseActionInput
# ---------------------------------------------------------------------------


class TestParseActionInput:
    def test_basic_extraction(self) -> None:
        """Standard ACTION/INPUT block returns correct tuple."""
        content = (
            "THOUGHT: I need consensus data.\n"
            'ACTION: consensus_summary\n'
            'INPUT: {"cycle_id": "abc123"}'
        )
        action, input_json = _parse_action_input(content)
        assert action == "consensus_summary"
        assert input_json == '{"cycle_id": "abc123"}'

    def test_no_action_returns_none(self) -> None:
        """Prose with no ACTION: returns (None, None)."""
        content = "I think the market is bullish based on strong fundamentals."
        action, input_json = _parse_action_input(content)
        assert action is None
        assert input_json is None

    def test_action_without_input_defaults_empty_json(self) -> None:
        """ACTION present, no INPUT line returns (action, '{}')."""
        content = "THOUGHT: Done.\nACTION: FINAL_ANSWER"
        action, input_json = _parse_action_input(content)
        assert action == "FINAL_ANSWER"
        assert input_json == "{}"

    def test_thought_before_action_parsed_correctly(self) -> None:
        """THOUGHT text before ACTION block still extracts correctly."""
        content = (
            "THOUGHT: I need to look at bracket breakdowns.\n"
            "Some additional reasoning here.\n"
            'ACTION: bracket_narratives\n'
            'INPUT: {"cycle_id": "xyz"}'
        )
        action, input_json = _parse_action_input(content)
        assert action == "bracket_narratives"
        assert input_json == '{"cycle_id": "xyz"}'


# ---------------------------------------------------------------------------
# Task 15-01-02: TestReportEngine (stubs filled in Task 15-01-02)
# ---------------------------------------------------------------------------


class TestReportEngine:
    async def test_terminates_on_final_answer(self) -> None:
        """Engine terminates immediately when LLM outputs FINAL_ANSWER."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(return_value=_mock_ollama_response(
            "THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}"
        ))

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # FINAL_ANSWER produces no observation
        assert result == []
        # Chat called once
        assert mock_client.chat.call_count == 1

    async def test_hard_cap_termination(self) -> None:
        """Engine exits at MAX_ITERATIONS when no FINAL_ANSWER."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()

        # Return incrementing inputs to avoid duplicate detection
        def make_response(i: int) -> MagicMock:
            return _mock_ollama_response(
                f'ACTION: bracket_summary\nINPUT: {{"cycle_id": "abc", "n": {i}}}'
            )

        mock_client.chat = AsyncMock(side_effect=[make_response(i) for i in range(MAX_ITERATIONS + 5)])

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        assert len(result) == MAX_ITERATIONS
        assert mock_client.chat.call_count == MAX_ITERATIONS

    async def test_duplicate_call_terminates(self) -> None:
        """Engine exits on duplicate (tool, input) pair after 1 successful call."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()
        # Always return the same response -> duplicate on second call
        mock_client.chat = AsyncMock(return_value=_mock_ollama_response(
            'ACTION: bracket_summary\nINPUT: {"cycle_id": "abc"}'
        ))

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # First call succeeds, second is duplicate -> exit
        assert len(result) == 1
        # First call dispatched, second detected as duplicate
        assert mock_client.chat.call_count == 2


# ---------------------------------------------------------------------------
# Task 15-01-03: TestGraphQueryTools (stubs filled in Task 15-01-03)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Mock AsyncDriver with session context manager support."""
    driver = MagicMock()
    driver.close = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session
    return driver


@pytest.fixture()
def mock_personas() -> list:
    """Empty personas list — report queries don't use personas."""
    return []


class TestGraphQueryTools:
    async def test_read_consensus_summary(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_consensus_summary returns dict with correct keys and values."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value={
            "buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100,
        })

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_consensus_summary("cycle1")

        assert result["buy_count"] == 50
        assert result["sell_count"] == 30
        assert result["hold_count"] == 20
        assert result["total"] == 100

    async def test_influence_leaders_round_filter(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_influence_leaders returns list with correct field structure."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[{
            "agent_id": "a1",
            "name": "Agent 1",
            "bracket": "Quants",
            "total_influence_weight": 0.9,
            "citation_count": 5,
        }])

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_influence_leaders("cycle1")

        assert len(result) == 1
        assert result[0]["agent_id"] == "a1"
        assert result[0]["name"] == "Agent 1"
        assert result[0]["bracket"] == "Quants"
        assert result[0]["total_influence_weight"] == 0.9
        assert result[0]["citation_count"] == 5

    async def test_signal_flip_none_filter(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_signal_flips returns list; NONE flip_types excluded by Cypher."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[{
            "agent_id": "a1",
            "name": "Agent 1",
            "bracket": "Quants",
            "round_num": 2,
            "flip_type": "HOLD_TO_BUY",
            "final_signal": "BUY",
        }])

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_signal_flips("cycle1")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["flip_type"] == "HOLD_TO_BUY"


# ---------------------------------------------------------------------------
# Task Plan 02: TestReportAssembler (stubs — filled in Plan 02)
# ---------------------------------------------------------------------------


class TestReportAssembler:
    def test_renders_section(self) -> None:
        """ReportAssembler.render_section returns markdown with section heading and data values."""
        from alphaswarm.report import ReportAssembler

        assembler = ReportAssembler()
        data = {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        result = assembler.render_section("01_consensus_summary.j2", data=data, cycle_id="test-cycle")

        assert "Consensus Summary" in result
        assert "50" in result
        assert "30" in result

    async def test_async_file_write(self, tmp_path: pytest.TempdirFactory) -> None:
        """write_report creates file with correct content using aiofiles."""
        from alphaswarm.report import write_report

        report_path = tmp_path / "test_report.md"  # type: ignore[operator]
        await write_report(report_path, "# Report Content")

        assert report_path.exists()
        assert report_path.read_text() == "# Report Content"

    async def test_sentinel_file_schema(self, tmp_path: pytest.TempdirFactory) -> None:
        """write_sentinel creates JSON with cycle_id, path, and generated_at ISO timestamp."""
        import json
        from datetime import datetime
        from alphaswarm.report import write_sentinel

        await write_sentinel("cycle1", "./reports/cycle1_report.md", sentinel_dir=tmp_path)  # type: ignore[arg-type]

        sentinel_file = tmp_path / "last_report.json"  # type: ignore[operator]
        assert sentinel_file.exists()

        data = json.loads(sentinel_file.read_text())
        assert set(data.keys()) == {"cycle_id", "path", "generated_at"}
        assert data["cycle_id"] == "cycle1"
        assert data["path"] == "./reports/cycle1_report.md"
        # Validate ISO timestamp
        datetime.fromisoformat(data["generated_at"])
