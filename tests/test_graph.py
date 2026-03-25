"""Unit tests for GraphStateManager and PeerDecision."""

from __future__ import annotations

import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.errors import Neo4jConnectionError, Neo4jWriteError
from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SignalType


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Create a mock AsyncDriver with session context manager support.

    neo4j's AsyncDriver.session() is a regular (non-async) method that returns
    an AsyncSession (async context manager). We use MagicMock for the driver
    so that session() is synchronous, and AsyncMock for the session itself
    so it supports __aenter__/__aexit__.
    """
    driver = MagicMock()
    driver.close = AsyncMock()  # close() is async
    session = AsyncMock()
    # session() is a regular call that returns an async context manager
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session
    return driver


@pytest.fixture()
def sample_personas_for_graph() -> list[AgentPersona]:
    """Create 2 test AgentPersona objects for seed_agents testing."""
    return [
        AgentPersona(
            id="quants_01",
            name="Quants 1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="test prompt quants",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01",
            name="Degens 1",
            bracket=BracketType.DEGENS,
            risk_profile=0.95,
            temperature=1.2,
            system_prompt="test prompt degens",
            influence_weight_base=0.3,
        ),
    ]


def test_init_stores_driver_and_database(mock_driver: MagicMock) -> None:
    """GraphStateManager.__init__ stores driver and database."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[], database="testdb")
    assert gsm._driver is mock_driver
    assert gsm._database == "testdb"


@pytest.mark.asyncio()
async def test_ensure_schema_runs_all_statements(mock_driver: MagicMock) -> None:
    """ensure_schema runs all SCHEMA_STATEMENTS then calls seed_agents."""
    from alphaswarm.graph import SCHEMA_STATEMENTS, GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with patch.object(gsm, "seed_agents", new_callable=AsyncMock) as mock_seed:
        await gsm.ensure_schema()

    # session.run called once per schema statement
    assert session.run.await_count == len(SCHEMA_STATEMENTS)
    # seed_agents called once after schema
    mock_seed.assert_awaited_once()


@pytest.mark.asyncio()
async def test_seed_agents_transforms_personas_to_dicts(
    mock_driver: MagicMock,
    sample_personas_for_graph: list[AgentPersona],
) -> None:
    """seed_agents transforms AgentPersona list to dicts and calls execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=sample_personas_for_graph)

    await gsm.seed_agents(sample_personas_for_graph)

    # execute_write was called
    session.execute_write.assert_awaited_once()
    # Extract the args passed to execute_write
    call_args = session.execute_write.call_args
    # The second positional arg (after tx function) should be the agents list
    agents_param = call_args[0][1]  # positional args: (tx_func, agents)
    assert len(agents_param) == 2
    expected_keys = {"id", "name", "bracket", "risk_profile", "temperature", "influence_weight_base"}
    for agent_dict in agents_param:
        assert set(agent_dict.keys()) == expected_keys
    # Verify bracket is the string value, not the enum
    assert agents_param[0]["bracket"] == "quants"
    assert agents_param[1]["bracket"] == "degens"


@pytest.mark.asyncio()
async def test_create_cycle_returns_uuid_string(mock_driver: MagicMock) -> None:
    """create_cycle returns a uuid4 string and calls execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    cycle_id = await gsm.create_cycle("test rumor")

    # Validate UUID4 format
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, cycle_id), f"Not a valid UUID4: {cycle_id}"
    # execute_write was called
    session.execute_write.assert_awaited_once()


@pytest.mark.asyncio()
async def test_close_calls_driver_close(mock_driver: MagicMock) -> None:
    """close() calls driver.close()."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    await gsm.close()

    mock_driver.close.assert_awaited_once()


def test_peer_decision_is_frozen_dataclass() -> None:
    """PeerDecision is a frozen dataclass with 6 fields."""
    from alphaswarm.graph import PeerDecision

    pd = PeerDecision(
        agent_id="quants_01",
        bracket="quants",
        signal="buy",
        confidence=0.8,
        sentiment=0.5,
        rationale="test rationale",
    )

    # Verify all 6 fields
    assert pd.agent_id == "quants_01"
    assert pd.bracket == "quants"
    assert pd.signal == "buy"
    assert pd.confidence == 0.8
    assert pd.sentiment == 0.5
    assert pd.rationale == "test rationale"

    # Verify frozen (assigning raises)
    assert dataclasses.is_dataclass(pd)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pd.agent_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Plan 02: write_decisions tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_agent_decisions() -> list[tuple[str, AgentDecision]]:
    """Create 3 test (agent_id, AgentDecision) tuples."""
    return [
        (
            "quants_01",
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.8,
                sentiment=0.5,
                rationale="bullish signal",
                cited_agents=["degens_01"],
            ),
        ),
        (
            "degens_01",
            AgentDecision(
                signal=SignalType.SELL,
                confidence=0.6,
                sentiment=-0.3,
                rationale="bearish momentum",
                cited_agents=[],
            ),
        ),
        (
            "macro_01",
            AgentDecision(
                signal=SignalType.HOLD,
                confidence=0.5,
                sentiment=0.0,
                rationale="neutral stance",
                cited_agents=["quants_01", "degens_01"],
            ),
        ),
    ]


@pytest.mark.asyncio()
async def test_write_decisions_single_transaction(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """write_decisions calls execute_write exactly once (single transaction)."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1)

    session.execute_write.assert_awaited_once()


@pytest.mark.asyncio()
async def test_write_decisions_generates_client_side_uuids(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """write_decisions generates client-side uuid4 for each decision_id."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1)

    call_args = session.execute_write.call_args
    # Params list is second positional arg (after tx function)
    params = call_args[0][1]
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    for p in params:
        assert re.match(uuid4_pattern, p["decision_id"]), f"Not a valid UUID4: {p['decision_id']}"


@pytest.mark.asyncio()
async def test_write_decisions_transforms_signal_to_value(
    mock_driver: MagicMock,
) -> None:
    """write_decisions converts SignalType enum to its string value."""
    from alphaswarm.graph import GraphStateManager

    decisions = [
        (
            "quants_01",
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.8,
                sentiment=0.5,
                rationale="test",
            ),
        ),
    ]
    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_decisions(decisions, "test-cycle-id", 1)

    call_args = session.execute_write.call_args
    params = call_args[0][1]
    assert params[0]["signal"] == "buy"


@pytest.mark.asyncio()
async def test_batch_write_tx_skips_cited_when_empty() -> None:
    """_batch_write_decisions_tx calls tx.run once when all cited_agents are empty."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    decisions = [
        {"decision_id": "d1", "agent_id": "a1", "signal": "buy", "confidence": 0.5,
         "sentiment": 0.0, "rationale": "test", "cited_agents": []},
        {"decision_id": "d2", "agent_id": "a2", "signal": "sell", "confidence": 0.6,
         "sentiment": -0.1, "rationale": "test", "cited_agents": []},
    ]

    await GraphStateManager._batch_write_decisions_tx(tx, decisions, "cycle-1", 1)

    # Only 1 tx.run call (Decision creation, no CITED)
    assert tx.run.await_count == 1


@pytest.mark.asyncio()
async def test_batch_write_tx_creates_cited_when_present() -> None:
    """_batch_write_decisions_tx calls tx.run twice when cited_agents are non-empty."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    decisions = [
        {"decision_id": "d1", "agent_id": "a1", "signal": "buy", "confidence": 0.5,
         "sentiment": 0.0, "rationale": "test", "cited_agents": ["a2"]},
    ]

    await GraphStateManager._batch_write_decisions_tx(tx, decisions, "cycle-1", 1)

    # 2 tx.run calls (Decision creation + CITED creation)
    assert tx.run.await_count == 2


@pytest.mark.asyncio()
async def test_read_peer_decisions_returns_peer_decision_list(
    mock_driver: MagicMock,
) -> None:
    """read_peer_decisions returns list[PeerDecision] from execute_read results."""
    from alphaswarm.graph import GraphStateManager, PeerDecision

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(
        return_value=[
            {"agent_id": "sovereigns_01", "bracket": "sovereigns", "signal": "hold",
             "confidence": 0.9, "sentiment": 0.1, "rationale": "stable outlook"},
            {"agent_id": "whales_01", "bracket": "whales", "signal": "buy",
             "confidence": 0.85, "sentiment": 0.4, "rationale": "bullish long-term"},
        ]
    )
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.read_peer_decisions("quants_01", "test-cycle", 1, limit=5)

    assert len(result) == 2
    assert all(isinstance(r, PeerDecision) for r in result)
    assert result[0].agent_id == "sovereigns_01"
    assert result[0].bracket == "sovereigns"
    assert result[1].signal == "buy"


@pytest.mark.asyncio()
async def test_read_peer_decisions_passes_parameters(
    mock_driver: MagicMock,
) -> None:
    """read_peer_decisions passes correct parameters to execute_read."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=[])
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.read_peer_decisions("quants_01", "test-uuid", 1, limit=5)

    session.execute_read.assert_awaited_once()
    call_args = session.execute_read.call_args
    # Positional args: (tx_func, agent_id, cycle_id, round_num, limit)
    assert call_args[0][1] == "quants_01"
    assert call_args[0][2] == "test-uuid"
    assert call_args[0][3] == 1
    assert call_args[0][4] == 5


@pytest.mark.asyncio()
async def test_write_decisions_wraps_neo4j_error(
    mock_driver: MagicMock,
) -> None:
    """write_decisions wraps neo4j.exceptions.Neo4jError as Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    original_exc = Neo4jError("simulated failure")
    session.execute_write = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5)),
    ]

    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.write_decisions(decisions, "test-cycle", 1)

    assert exc_info.value.original_error is original_exc


@pytest.mark.asyncio()
async def test_read_peer_decisions_wraps_neo4j_error(
    mock_driver: MagicMock,
) -> None:
    """read_peer_decisions wraps neo4j.exceptions.Neo4jError as Neo4jConnectionError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    original_exc = Neo4jError("simulated failure")
    session.execute_read = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jConnectionError) as exc_info:
        await gsm.read_peer_decisions("quants_01", "test-cycle", 1)

    assert exc_info.value.original_error is original_exc
