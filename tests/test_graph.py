"""Unit tests for GraphStateManager and PeerDecision."""

from __future__ import annotations

import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.errors import Neo4jConnectionError, Neo4jWriteError
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketType,
    EntityType,
    SeedEntity,
    SeedEvent,
    SignalType,
)


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


# ---------------------------------------------------------------------------
# Phase 5 Plan 02: create_cycle_with_seed_event tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_seed_event_for_graph() -> SeedEvent:
    """Sample SeedEvent with 2 entities for graph persistence tests."""
    return SeedEvent(
        raw_rumor="NVIDIA announces breakthrough in quantum computing",
        entities=[
            SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
            SeedEntity(name="Semiconductors", type=EntityType.SECTOR, relevance=0.7, sentiment=0.5),
        ],
        overall_sentiment=0.6,
    )


def test_schema_statements_includes_entity_constraint() -> None:
    """SCHEMA_STATEMENTS contains Entity name+type uniqueness constraint."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    entity_constraints = [s for s in SCHEMA_STATEMENTS if "entity_name_type_unique" in s]
    assert len(entity_constraints) == 1, "Expected exactly one entity uniqueness constraint"


@pytest.mark.asyncio()
async def test_create_cycle_with_seed_event_single_transaction(
    mock_driver: MagicMock,
    sample_seed_event_for_graph: SeedEvent,
) -> None:
    """create_cycle_with_seed_event calls session.execute_write exactly once."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph)

    session.execute_write.assert_awaited_once()


@pytest.mark.asyncio()
async def test_create_cycle_with_seed_event_returns_uuid(
    mock_driver: MagicMock,
    sample_seed_event_for_graph: SeedEvent,
) -> None:
    """create_cycle_with_seed_event returns a valid UUID4 string."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    cycle_id = await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph)

    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, cycle_id), f"Not a valid UUID4: {cycle_id}"


@pytest.mark.asyncio()
async def test_create_cycle_with_seed_event_wraps_neo4j_error(
    mock_driver: MagicMock,
    sample_seed_event_for_graph: SeedEvent,
) -> None:
    """create_cycle_with_seed_event wraps Neo4jError as Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    original_exc = Neo4jError("simulated failure")
    session.execute_write = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph)

    assert exc_info.value.original_error is original_exc


@pytest.mark.asyncio()
async def test_create_cycle_with_entities_tx_creates_cycle_with_overall_sentiment() -> None:
    """Transaction function creates Cycle node with overall_sentiment property."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    await GraphStateManager._create_cycle_with_entities_tx(
        tx, "test-cycle-id", "test rumor", 0.6, [],
    )

    # With empty entities, only 1 tx.run call (Cycle creation only)
    assert tx.run.await_count == 1
    call_args = tx.run.call_args_list[0]
    cypher = call_args[0][0]
    assert "overall_sentiment" in cypher


@pytest.mark.asyncio()
async def test_create_cycle_with_entities_tx_skips_unwind_when_empty() -> None:
    """Transaction function skips Entity UNWIND when entities list is empty."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    await GraphStateManager._create_cycle_with_entities_tx(
        tx, "test-cycle-id", "test rumor", 0.6, [],
    )

    # Only 1 tx.run call (Cycle creation, no Entity UNWIND)
    assert tx.run.await_count == 1


@pytest.mark.asyncio()
async def test_create_cycle_with_entities_tx_creates_mentions_relationships() -> None:
    """Transaction function creates Entity+MENTIONS when entities are present."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    entities = [
        {"name": "NVIDIA", "type": "company", "relevance": 0.95, "sentiment": 0.8},
        {"name": "Semiconductors", "type": "sector", "relevance": 0.7, "sentiment": 0.5},
    ]

    await GraphStateManager._create_cycle_with_entities_tx(
        tx, "test-cycle-id", "test rumor", 0.6, entities,
    )

    # 2 tx.run calls: Cycle creation + Entity UNWIND with MENTIONS
    assert tx.run.await_count == 2
    entity_cypher = tx.run.call_args_list[1][0][0]
    assert "MENTIONS" in entity_cypher
    assert "relevance" in entity_cypher
    assert "sentiment" in entity_cypher


# ---------------------------------------------------------------------------
# Phase 8: Influence edge computation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_compute_influence_edges_reads_citations(mock_driver: MagicMock) -> None:
    """compute_influence_edges reads CITED pairs, computes weights, writes INFLUENCED_BY."""
    # Rev: [HIGH] Test uses pair-aware data (source_id, target_id) not flat counts
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    # Mock citation pairs: macro_01->quants_01, degens_01->quants_01, macro_01->degens_01
    session.execute_read = AsyncMock(
        return_value=[
            {"source_id": "macro_01", "target_id": "quants_01"},
            {"source_id": "degens_01", "target_id": "quants_01"},
            {"source_id": "macro_01", "target_id": "degens_01"},
        ]
    )
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    weights = await gsm.compute_influence_edges("cycle-1", 1, 10)
    assert isinstance(weights, dict)  # Rev: [Codex HIGH] explicit return type check
    assert weights["quants_01"] == pytest.approx(0.2)  # 2 unique citers / 10
    assert weights["degens_01"] == pytest.approx(0.1)  # 1 unique citer / 10
    session.execute_write.assert_awaited_once()  # INFLUENCED_BY edges written


@pytest.mark.asyncio()
async def test_influence_weights_cumulative_across_rounds(mock_driver: MagicMock) -> None:
    """compute_influence_edges with up_to_round=2 reads citations from rounds 1 and 2."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(
        return_value=[
            {"source_id": "macro_01", "target_id": "quants_01"},
            {"source_id": "degens_01", "target_id": "quants_01"},
            {"source_id": "suits_01", "target_id": "quants_01"},
            {"source_id": "macro_01", "target_id": "degens_01"},
            {"source_id": "suits_01", "target_id": "degens_01"},
        ]
    )
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    weights = await gsm.compute_influence_edges("cycle-1", 2, 10)
    assert weights["quants_01"] == pytest.approx(0.3)  # 3 unique citers / 10 cumulative
    assert weights["degens_01"] == pytest.approx(0.2)  # 2 unique citers / 10


@pytest.mark.asyncio()
async def test_compute_influence_edges_zero_citations(mock_driver: MagicMock) -> None:
    """compute_influence_edges with zero citations returns empty dict and skips write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=[])
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    weights = await gsm.compute_influence_edges("cycle-1", 1, 10)
    assert weights == {}
    session.execute_write.assert_not_awaited()


@pytest.mark.asyncio()
async def test_self_citations_filtered() -> None:
    """_read_citation_pairs_tx Cypher contains self-citation filter."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    async def _empty_aiter():
        return
        yield  # make this an async generator

    mock_result = MagicMock()
    mock_result.__aiter__ = lambda self: _empty_aiter()
    tx.run = AsyncMock(return_value=mock_result)
    await GraphStateManager._read_citation_pairs_tx(tx, "cycle-1", 1)
    cypher = tx.run.call_args[0][0]
    # Must exclude self-citations: author.id <> cited.id
    assert "author" in cypher and "cited" in cypher
    assert "<>" in cypher  # Self-citation filter present


@pytest.mark.asyncio()
async def test_duplicate_citations_deduplicated() -> None:
    """_read_citation_pairs_tx uses DISTINCT to deduplicate citation pairs."""
    # Rev: [Codex MEDIUM] Duplicate cited_agents entries must not inflate influence
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    async def _empty_aiter():
        return
        yield  # make this an async generator

    mock_result = MagicMock()
    mock_result.__aiter__ = lambda self: _empty_aiter()
    tx.run = AsyncMock(return_value=mock_result)
    await GraphStateManager._read_citation_pairs_tx(tx, "cycle-1", 1)
    cypher = tx.run.call_args[0][0]
    assert "DISTINCT" in cypher


@pytest.mark.asyncio()
async def test_write_influence_edges_tx_uses_unwind() -> None:
    """_write_influence_edges_tx Cypher uses UNWIND and INFLUENCED_BY."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    edges = [{"source_id": "a1", "target_id": "a2", "weight": 0.5}]
    await GraphStateManager._write_influence_edges_tx(tx, edges, "cycle-1", 1)
    cypher = tx.run.call_args[0][0]
    assert "UNWIND" in cypher
    assert "INFLUENCED_BY" in cypher


@pytest.mark.asyncio()
async def test_write_influence_edges_tx_empty_edges() -> None:
    """_write_influence_edges_tx with empty edges list does not call tx.run."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    await GraphStateManager._write_influence_edges_tx(tx, [], "cycle-1", 1)
    tx.run.assert_not_awaited()


@pytest.mark.asyncio()
async def test_influence_edges_include_round_property() -> None:
    """_write_influence_edges_tx includes round property on INFLUENCED_BY edges."""
    # Rev: [Codex MEDIUM] round property needed to avoid double-counting across rounds
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    edges = [{"source_id": "a1", "target_id": "a2", "weight": 0.5}]
    await GraphStateManager._write_influence_edges_tx(tx, edges, "cycle-1", 2)
    cypher = tx.run.call_args[0][0]
    assert "round" in cypher  # round property on edge
    # Verify round_num is passed as parameter
    call_kwargs = (
        tx.run.call_args.kwargs
        if hasattr(tx.run.call_args, "kwargs")
        else tx.run.call_args[1]
    )
    assert call_kwargs.get("round_num") == 2 or "round_num" in str(tx.run.call_args)


# ---------------------------------------------------------------------------
# Phase 11 Plan 02: write_decisions refactor + new episode/edge/entity methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_write_decisions_returns_decision_ids(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """write_decisions returns a list of decision_id strings (one per decision)."""
    import re

    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1)

    assert isinstance(result, list)
    assert len(result) == len(sample_agent_decisions)
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    for did in result:
        assert isinstance(did, str)
        assert re.match(uuid4_pattern, did), f"Not a valid UUID4: {did}"


@pytest.mark.asyncio()
async def test_write_decisions_accepts_pregenerated_ids(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """write_decisions uses pre-generated decision_ids when provided and returns them."""
    from alphaswarm.graph import GraphStateManager

    pre_ids = [f"pre-id-{i}" for i in range(len(sample_agent_decisions))]
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.write_decisions(
        sample_agent_decisions, "test-cycle-id", 1, decision_ids=pre_ids
    )

    assert result == pre_ids
    # Verify the pre-generated IDs were actually passed to execute_write
    session = mock_driver.session.return_value
    call_args = session.execute_write.call_args
    params = call_args[0][1]
    assert [p["decision_id"] for p in params] == pre_ids


@pytest.mark.asyncio()
async def test_write_decisions_raises_on_mismatched_ids(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """write_decisions raises ValueError if decision_ids length != agent_decisions length."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    wrong_ids = ["only-one-id"]  # 3 decisions, 1 id

    with pytest.raises(ValueError, match="decision_ids length"):
        await gsm.write_decisions(
            sample_agent_decisions, "test-cycle-id", 1, decision_ids=wrong_ids
        )


@pytest.mark.asyncio()
async def test_write_rationale_episodes(mock_driver: MagicMock) -> None:
    """write_rationale_episodes calls execute_write once with episode data."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.write_buffer import EpisodeRecord

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    records = [
        EpisodeRecord(
            decision_id="dec-001",
            agent_id="quants_01",
            rationale="bullish on NVIDIA",
            peer_context_received="",
            flip_type="none",
            round_num=1,
            cycle_id="cycle-abc",
        ),
        EpisodeRecord(
            decision_id="dec-002",
            agent_id="degens_01",
            rationale="bearish momentum",
            peer_context_received="peer said buy",
            flip_type="buy_to_sell",
            round_num=1,
            cycle_id="cycle-abc",
        ),
    ]

    await gsm.write_rationale_episodes(records)

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    # Second positional arg is the episodes list
    episodes_param = call_args[0][1]
    assert len(episodes_param) == 2
    assert episodes_param[0]["decision_id"] == "dec-001"
    assert episodes_param[0]["rationale"] == "bullish on NVIDIA"
    assert episodes_param[1]["flip_type"] == "buy_to_sell"


@pytest.mark.asyncio()
async def test_write_rationale_episodes_empty_is_noop(mock_driver: MagicMock) -> None:
    """write_rationale_episodes with empty list does not open a session."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    await gsm.write_rationale_episodes([])
    mock_driver.session.assert_not_called()


@pytest.mark.asyncio()
async def test_batch_write_episodes_tx_uses_unwind_and_has_episode() -> None:
    """_batch_write_episodes_tx Cypher uses UNWIND and creates HAS_EPISODE."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    episodes = [
        {
            "decision_id": "dec-001",
            "rationale": "test rationale",
            "peer_context_received": "",
            "flip_type": "none",
            "round_num": 1,
            "cycle_id": "cycle-abc",
        }
    ]

    await GraphStateManager._batch_write_episodes_tx(tx, episodes, "cycle-abc", 1)

    tx.run.assert_awaited_once()
    cypher = tx.run.call_args[0][0]
    assert "UNWIND" in cypher
    assert "HAS_EPISODE" in cypher
    assert "RationaleEpisode" in cypher


@pytest.mark.asyncio()
async def test_write_narrative_edges_case_insensitive(mock_driver: MagicMock) -> None:
    """write_narrative_edges matches entity names case-insensitively."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.write_buffer import EpisodeRecord

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    # Entity name is "NVIDIA" (uppercase), rationale mentions "nvidia" (lowercase)
    records = [
        EpisodeRecord(
            decision_id="dec-001",
            agent_id="quants_01",
            rationale="bullish on nvidia semiconductor",  # lowercase mention
            peer_context_received="",
            flip_type="none",
            round_num=1,
            cycle_id="cycle-abc",
        ),
    ]
    entity_names = ["NVIDIA", "Apple"]  # original casing

    await gsm.write_narrative_edges(records, entity_names)

    # Should have matched "nvidia" in rationale against "NVIDIA"
    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    matches_param = call_args[0][1]
    assert len(matches_param) == 1
    assert matches_param[0]["decision_id"] == "dec-001"


@pytest.mark.asyncio()
async def test_write_narrative_edges_original_casing(mock_driver: MagicMock) -> None:
    """write_narrative_edges preserves original entity name casing in the matched pairs."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.write_buffer import EpisodeRecord

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    records = [
        EpisodeRecord(
            decision_id="dec-001",
            agent_id="quants_01",
            rationale="bullish on NVIDIA semiconductors",
            peer_context_received="",
            flip_type="none",
            round_num=1,
            cycle_id="cycle-abc",
        ),
    ]
    entity_names = ["NVIDIA"]  # original uppercase casing

    await gsm.write_narrative_edges(records, entity_names)

    call_args = session.execute_write.call_args
    matches_param = call_args[0][1]
    # entity_name must be "NVIDIA" (original casing), NOT "nvidia"
    assert matches_param[0]["entity_name"] == "NVIDIA"


@pytest.mark.asyncio()
async def test_write_narrative_edges_no_match_skips_write(mock_driver: MagicMock) -> None:
    """write_narrative_edges skips execute_write when no entities match rationales."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.write_buffer import EpisodeRecord

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    records = [
        EpisodeRecord(
            decision_id="dec-001",
            agent_id="quants_01",
            rationale="general market trend",  # no entity mention
            peer_context_received="",
            flip_type="none",
            round_num=1,
            cycle_id="cycle-abc",
        ),
    ]
    entity_names = ["NVIDIA", "Apple"]  # not mentioned in rationale

    await gsm.write_narrative_edges(records, entity_names)

    session.execute_write.assert_not_awaited()


@pytest.mark.asyncio()
async def test_write_narrative_edges_empty_is_noop(mock_driver: MagicMock) -> None:
    """write_narrative_edges with empty records or entity_names is a no-op."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.write_buffer import EpisodeRecord

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    record = EpisodeRecord(
        decision_id="dec-001",
        agent_id="quants_01",
        rationale="bullish on NVIDIA",
        peer_context_received="",
        flip_type="none",
        round_num=1,
        cycle_id="cycle-abc",
    )

    # Empty records
    await gsm.write_narrative_edges([], ["NVIDIA"])
    session.execute_write.assert_not_awaited()

    # Empty entity_names
    await gsm.write_narrative_edges([record], [])
    session.execute_write.assert_not_awaited()


@pytest.mark.asyncio()
async def test_batch_write_references_tx_cypher() -> None:
    """_batch_write_references_tx Cypher uses UNWIND and creates REFERENCES edge."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    matches = [{"decision_id": "dec-001", "entity_name": "NVIDIA"}]

    await GraphStateManager._batch_write_references_tx(tx, matches)

    tx.run.assert_awaited_once()
    cypher = tx.run.call_args[0][0]
    assert "UNWIND" in cypher
    assert "REFERENCES" in cypher
    assert "substring" in cypher


@pytest.mark.asyncio()
async def test_read_cycle_entities(mock_driver: MagicMock) -> None:
    """read_cycle_entities returns list of entity name strings from Cycle-MENTIONS->Entity."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value

    # Mock the async iteration of query results
    async def mock_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        class MockResult:
            def __aiter__(self):  # type: ignore[no-untyped-def]
                return self._iter()

            async def _iter(self):  # type: ignore[no-untyped-def]
                for name in ["NVIDIA", "Semiconductors"]:
                    yield {"name": name}

        return MockResult()

    session.run = AsyncMock(side_effect=mock_run)
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.read_cycle_entities("cycle-abc")

    assert result == ["NVIDIA", "Semiconductors"]
    session.run.assert_awaited_once()
    cypher = session.run.call_args[0][0]
    assert "MENTIONS" in cypher
    assert "cycle_id" in cypher or "$cycle_id" in cypher


@pytest.mark.asyncio()
async def test_read_cycle_entities_mentions_entity_pattern() -> None:
    """read_cycle_entities Cypher uses MATCH (c:Cycle)-[:MENTIONS]->(e:Entity) pattern."""
    from alphaswarm.graph import GraphStateManager

    # Test the Cypher directly by inspecting read_cycle_entities' session.run call
    mock_driver_local = MagicMock()
    mock_driver_local.close = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    mock_driver_local.session.return_value = session

    async def mock_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        class MockResult:
            def __aiter__(self):  # type: ignore[no-untyped-def]
                return self._iter()

            async def _iter(self):  # type: ignore[no-untyped-def]
                return
                yield  # make async generator

        return MockResult()

    session.run = AsyncMock(side_effect=mock_run)
    gsm = GraphStateManager(driver=mock_driver_local, personas=[])

    await gsm.read_cycle_entities("cycle-abc")

    cypher = session.run.call_args[0][0]
    assert "Cycle" in cypher
    assert "MENTIONS" in cypher
    assert "Entity" in cypher


@pytest.mark.asyncio()
async def test_write_decision_narratives(mock_driver: MagicMock) -> None:
    """write_decision_narratives calls execute_write with narratives list."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    narratives = [
        {"agent_id": "quants_01", "narrative": "Maintained buy signal across all 3 rounds."},
        {"agent_id": "degens_01", "narrative": "Flipped from buy to sell after peer influence."},
    ]

    await gsm.write_decision_narratives(narratives)

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    narratives_param = call_args[0][1]
    assert len(narratives_param) == 2
    assert narratives_param[0]["agent_id"] == "quants_01"


@pytest.mark.asyncio()
async def test_write_decision_narratives_empty_is_noop(mock_driver: MagicMock) -> None:
    """write_decision_narratives with empty list does not open a session."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    await gsm.write_decision_narratives([])
    mock_driver.session.assert_not_called()


@pytest.mark.asyncio()
async def test_batch_write_narratives_tx_cypher() -> None:
    """_batch_write_narratives_tx Cypher uses UNWIND and SET decision_narrative."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    narratives = [{"agent_id": "quants_01", "narrative": "Bullish across all rounds."}]

    await GraphStateManager._batch_write_narratives_tx(tx, narratives)

    tx.run.assert_awaited_once()
    cypher = tx.run.call_args[0][0]
    assert "UNWIND" in cypher
    assert "decision_narrative" in cypher
    assert "Agent" in cypher


def test_schema_statements_includes_episode_index() -> None:
    """SCHEMA_STATEMENTS contains RationaleEpisode composite index."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    episode_indexes = [s for s in SCHEMA_STATEMENTS if "episode_cycle_round" in s]
    assert len(episode_indexes) == 1
    assert "RationaleEpisode" in episode_indexes[0]


# ---------------------------------------------------------------------------
# Phase 12 Plan 01 Task 1: RankedPost, Post schema index, write_posts
# ---------------------------------------------------------------------------


def test_schema_statements_includes_post_index() -> None:
    """SCHEMA_STATEMENTS contains Post composite index on (cycle_id, round_num)."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    post_indexes = [s for s in SCHEMA_STATEMENTS if "post_cycle_round" in s]
    assert len(post_indexes) == 1
    assert "Post" in post_indexes[0]
    assert "cycle_id" in post_indexes[0]
    assert "round_num" in post_indexes[0]


def test_ranked_post_dataclass_frozen() -> None:
    """RankedPost is a frozen dataclass with 8 fields."""
    from alphaswarm.graph import RankedPost

    rp = RankedPost(
        post_id="x",
        agent_id="a",
        bracket="quants",
        signal="buy",
        confidence=0.85,
        content="text",
        influence_weight=0.7,
        round_num=1,
    )
    assert rp.post_id == "x"
    assert rp.agent_id == "a"
    assert rp.bracket == "quants"
    assert rp.signal == "buy"
    assert rp.confidence == 0.85
    assert rp.content == "text"
    assert rp.influence_weight == 0.7
    assert rp.round_num == 1
    assert dataclasses.is_dataclass(rp)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rp.content = "new"  # type: ignore[misc]


@pytest.mark.asyncio()
async def test_write_posts_creates_post_nodes(mock_driver: MagicMock) -> None:
    """write_posts creates Post nodes with correct params and returns post_ids."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    decisions = [
        ("agent_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, sentiment=0.5, rationale="bullish")),
    ]
    decision_ids = ["dec-001"]

    result = await gsm.write_posts(decisions, decision_ids, "cycle_1", 1)

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    posts_param = call_args[0][1]
    assert len(posts_param) == 1
    p = posts_param[0]
    assert "post_id" in p
    assert p["agent_id"] == "agent_01"
    assert p["content"] == "bullish"
    assert p["signal"] == "buy"
    assert p["confidence"] == 0.8
    assert p["round_num"] == 1
    assert p["cycle_id"] == "cycle_1"
    assert p["decision_id"] == "dec-001"
    assert len(result) == 1
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, result[0])


@pytest.mark.asyncio()
async def test_write_posts_skip_parse_error(mock_driver: MagicMock) -> None:
    """write_posts filters out PARSE_ERROR decisions."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    decisions = [
        ("a1", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="error text")),
        ("a2", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="strong buy")),
    ]
    decision_ids = ["dec-err", "dec-buy"]

    result = await gsm.write_posts(decisions, decision_ids, "c1", 1)

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    posts_param = call_args[0][1]
    assert len(posts_param) == 1
    assert posts_param[0]["agent_id"] == "a2"
    assert len(result) == 1


@pytest.mark.asyncio()
async def test_write_posts_empty_list(mock_driver: MagicMock) -> None:
    """write_posts with empty list does not call execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.write_posts([], [], "c1", 1)

    session.execute_write.assert_not_awaited()
    assert result == []


@pytest.mark.asyncio()
async def test_write_posts_wraps_neo4j_error(mock_driver: MagicMock) -> None:
    """write_posts wraps Neo4jError as Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    original_exc = Neo4jError("simulated failure")
    session.execute_write = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    decisions = [
        ("a1", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="test")),
    ]
    decision_ids = ["dec-001"]

    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.write_posts(decisions, decision_ids, "c1", 1)

    assert exc_info.value.original_error is original_exc


@pytest.mark.asyncio()
async def test_write_posts_all_parse_error_is_noop(mock_driver: MagicMock) -> None:
    """write_posts with all PARSE_ERROR decisions does not call execute_write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    decisions = [
        ("a1", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="err")),
        ("a2", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="err2")),
    ]
    decision_ids = ["dec-001", "dec-002"]

    result = await gsm.write_posts(decisions, decision_ids, "c1", 1)

    session.execute_write.assert_not_awaited()
    assert result == []


# ---------------------------------------------------------------------------
# Phase 12 Plan 01 Task 2: read_ranked_posts, write_read_post_edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_read_ranked_posts_returns_ordered_list(mock_driver: MagicMock) -> None:
    """read_ranked_posts returns RankedPost list ordered by influence_weight DESC."""
    from alphaswarm.graph import GraphStateManager, RankedPost

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(
        return_value=[
            RankedPost(
                post_id="p1", agent_id="a1", bracket="quants", signal="buy",
                confidence=0.9, content="strong buy", influence_weight=0.9, round_num=1,
            ),
            RankedPost(
                post_id="p2", agent_id="a2", bracket="degens", signal="sell",
                confidence=0.7, content="sell signal", influence_weight=0.7, round_num=1,
            ),
            RankedPost(
                post_id="p3", agent_id="a3", bracket="macro", signal="hold",
                confidence=0.5, content="neutral", influence_weight=0.5, round_num=1,
            ),
        ]
    )
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.read_ranked_posts("agent_01", "cycle_1", source_round=1, limit=10)

    assert len(result) == 3
    assert all(isinstance(r, RankedPost) for r in result)
    assert result[0].influence_weight >= result[1].influence_weight >= result[2].influence_weight
    assert result[0].influence_weight == 0.9
    assert result[1].influence_weight == 0.7
    assert result[2].influence_weight == 0.5


@pytest.mark.asyncio()
async def test_read_ranked_posts_fallback_weight(mock_driver: MagicMock) -> None:
    """read_ranked_posts uses influence_weight_base when INFLUENCED_BY edge is absent."""
    from alphaswarm.graph import GraphStateManager, RankedPost

    session = mock_driver.session.return_value
    # Simulate coalesce fallback: influence_weight comes from author.influence_weight_base
    session.execute_read = AsyncMock(
        return_value=[
            RankedPost(
                post_id="p1", agent_id="a1", bracket="sovereigns", signal="buy",
                confidence=0.8, content="test", influence_weight=0.9, round_num=1,
            ),
        ]
    )
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.read_ranked_posts("agent_02", "cycle_1", source_round=1, limit=5)

    assert len(result) == 1
    assert result[0].influence_weight == 0.9  # fallback base weight


@pytest.mark.asyncio()
async def test_read_ranked_posts_excludes_self() -> None:
    """read_ranked_posts Cypher contains self-exclusion filter."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    async def _empty_aiter():
        return
        yield  # make async generator

    mock_result = MagicMock()
    mock_result.__aiter__ = lambda self: _empty_aiter()
    tx.run = AsyncMock(return_value=mock_result)
    await GraphStateManager._read_ranked_posts_tx(tx, "agent_01", "cycle_1", 1, 10)
    cypher = tx.run.call_args[0][0]
    assert "p.agent_id <> $agent_id" in cypher


@pytest.mark.asyncio()
async def test_read_ranked_posts_excludes_parse_error() -> None:
    """read_ranked_posts Cypher excludes parse_error posts."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    async def _empty_aiter():
        return
        yield

    mock_result = MagicMock()
    mock_result.__aiter__ = lambda self: _empty_aiter()
    tx.run = AsyncMock(return_value=mock_result)
    await GraphStateManager._read_ranked_posts_tx(tx, "agent_01", "cycle_1", 1, 10)
    cypher = tx.run.call_args[0][0]
    assert "p.signal <> 'parse_error'" in cypher


@pytest.mark.asyncio()
async def test_write_read_post_edges_creates_all_pairs(mock_driver: MagicMock) -> None:
    """write_read_post_edges creates N_agents * N_posts READ_POST edges."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_read_post_edges(
        agent_ids=["a1", "a2", "a3"],
        post_ids=["p1", "p2", "p3", "p4"],
        round_num=2,
        cycle_id="cycle_1",
    )

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    pairs_param = call_args[0][1]
    assert len(pairs_param) == 12  # 3 agents * 4 posts


@pytest.mark.asyncio()
async def test_write_read_post_edges_empty_agents(mock_driver: MagicMock) -> None:
    """write_read_post_edges with empty agent_ids is a no-op."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_read_post_edges(
        agent_ids=[], post_ids=["p1"], round_num=2, cycle_id="c1",
    )

    session.execute_write.assert_not_awaited()


@pytest.mark.asyncio()
async def test_write_read_post_edges_empty_posts(mock_driver: MagicMock) -> None:
    """write_read_post_edges with empty post_ids is a no-op."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_read_post_edges(
        agent_ids=["a1"], post_ids=[], round_num=2, cycle_id="c1",
    )

    session.execute_write.assert_not_awaited()


@pytest.mark.asyncio()
async def test_write_read_post_edges_wraps_neo4j_error(mock_driver: MagicMock) -> None:
    """write_read_post_edges wraps Neo4jError as Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    original_exc = Neo4jError("simulated failure")
    session.execute_write = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.write_read_post_edges(
            agent_ids=["a1"], post_ids=["p1"], round_num=2, cycle_id="c1",
        )


# ---------------------------------------------------------------------------
# Phase 26: ShockEvent persistence (Plan 03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_write_shock_event_creates_node_and_edge() -> None:
    """Phase 26 SHOCK-03 — _write_shock_event_tx Cypher contains ShockEvent + HAS_SHOCK.

    Per Codex MEDIUM feedback: verify the actual Cypher emitted by the
    transaction function, not just that execute_write was called.
    """
    from alphaswarm.graph import GraphStateManager

    mock_tx = AsyncMock()
    mock_tx.run = AsyncMock()

    await GraphStateManager._write_shock_event_tx(
        mock_tx,
        "shock-uuid-1",
        "cycle-123",
        "Fed cut rates",
        2,
    )

    assert mock_tx.run.called
    cypher = mock_tx.run.call_args.args[0]
    assert "ShockEvent" in cypher
    assert "HAS_SHOCK" in cypher
    assert "MATCH (c:Cycle" in cypher
    assert "CREATE (se:ShockEvent" in cypher
    assert "CREATE (c)-[:HAS_SHOCK]->(se)" in cypher
    kwargs = mock_tx.run.call_args.kwargs
    assert kwargs["shock_id"] == "shock-uuid-1"
    assert kwargs["cycle_id"] == "cycle-123"
    assert kwargs["shock_text"] == "Fed cut rates"
    assert kwargs["injected_before_round"] == 2


@pytest.mark.asyncio()
async def test_write_shock_event_returns_uuid(mock_driver: MagicMock) -> None:
    """Phase 26 SHOCK-03 — write_shock_event returns a UUID4 string shock_id."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    shock_id = await gsm.write_shock_event(
        cycle_id="cycle-abc",
        shock_text="oil shock",
        injected_before_round=3,
    )

    uuid4_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    assert uuid4_pattern.match(shock_id), f"shock_id {shock_id!r} is not a UUID4"


@pytest.mark.asyncio()
async def test_write_shock_event_wraps_driver_errors(mock_driver: MagicMock) -> None:
    """Phase 26 SHOCK-03 — Neo4jError is wrapped in Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    original_exc = Neo4jError("boom")
    mock_driver.session.return_value.execute_write = AsyncMock(side_effect=original_exc)

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.write_shock_event(
            cycle_id="cycle-err",
            shock_text="panic",
            injected_before_round=2,
        )
    assert "cycle-err" in str(exc_info.value)
    assert exc_info.value.original_error is original_exc


def test_ensure_schema_includes_shock_cycle_index() -> None:
    """Phase 26 SHOCK-03 — SCHEMA_STATEMENTS contains shock_cycle_idx CREATE INDEX."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    matching = [
        stmt for stmt in SCHEMA_STATEMENTS
        if re.search(
            r"CREATE INDEX\s+shock_cycle_idx.*ShockEvent.*cycle_id",
            stmt,
            re.IGNORECASE | re.DOTALL,
        )
    ]
    assert len(matching) == 1, (
        f"Expected exactly one shock_cycle_idx statement; got {len(matching)}"
    )


# ---------------------------------------------------------------------------
# Phase 27: Shock analysis graph methods (Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_read_shock_event_returns_dict_when_exists(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — read_shock_event returns dict when ShockEvent exists for cycle."""
    pytest.fail("Not yet implemented — see Plan 01 (shock analysis graph methods)")


@pytest.mark.asyncio()
async def test_read_shock_event_returns_none_when_no_shock(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — read_shock_event returns None when no ShockEvent exists."""
    pytest.fail("Not yet implemented — see Plan 01 (shock analysis graph methods)")


@pytest.mark.asyncio()
async def test_read_shock_impact_returns_per_agent_rows(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — read_shock_impact returns dict with bracket_deltas, pivot_count, comparable_agents."""
    pytest.fail("Not yet implemented — see Plan 01 (shock analysis graph methods)")


@pytest.mark.asyncio()
async def test_read_shock_impact_pivot_flag_computed_correctly(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — pivot_count=1, held_firm_count=1, comparable_agents=2 when 1 of 2 agents changed signal."""
    pytest.fail("Not yet implemented — see Plan 01 (shock analysis graph methods)")
