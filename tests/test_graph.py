"""Unit tests for GraphStateManager and PeerDecision."""

from __future__ import annotations

import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import AgentPersona, BracketType


@pytest.fixture()
def mock_driver() -> AsyncMock:
    """Create a mock AsyncDriver with session context manager support."""
    driver = AsyncMock()
    session = AsyncMock()
    # session() returns an async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = ctx
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


def test_init_stores_driver_and_database(mock_driver: AsyncMock) -> None:
    """GraphStateManager.__init__ stores driver and database."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[], database="testdb")
    assert gsm._driver is mock_driver
    assert gsm._database == "testdb"


@pytest.mark.asyncio()
async def test_ensure_schema_runs_all_statements(mock_driver: AsyncMock) -> None:
    """ensure_schema runs all SCHEMA_STATEMENTS then calls seed_agents."""
    from alphaswarm.graph import SCHEMA_STATEMENTS, GraphStateManager

    session = await mock_driver.session.return_value.__aenter__()
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with patch.object(gsm, "seed_agents", new_callable=AsyncMock) as mock_seed:
        await gsm.ensure_schema()

    # session.run called once per schema statement
    assert session.run.await_count == len(SCHEMA_STATEMENTS)
    # seed_agents called once after schema
    mock_seed.assert_awaited_once()


@pytest.mark.asyncio()
async def test_seed_agents_transforms_personas_to_dicts(
    mock_driver: AsyncMock,
    sample_personas_for_graph: list[AgentPersona],
) -> None:
    """seed_agents transforms AgentPersona list to dicts and calls execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = await mock_driver.session.return_value.__aenter__()
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
async def test_create_cycle_returns_uuid_string(mock_driver: AsyncMock) -> None:
    """create_cycle returns a uuid4 string and calls execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = await mock_driver.session.return_value.__aenter__()
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    cycle_id = await gsm.create_cycle("test rumor")

    # Validate UUID4 format
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, cycle_id), f"Not a valid UUID4: {cycle_id}"
    # execute_write was called
    session.execute_write.assert_awaited_once()


@pytest.mark.asyncio()
async def test_close_calls_driver_close(mock_driver: AsyncMock) -> None:
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
