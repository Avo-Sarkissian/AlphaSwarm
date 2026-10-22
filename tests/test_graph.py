"""Unit tests for GraphStateManager."""

from __future__ import annotations

import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.errors import Neo4jWriteError
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


def _ack_rows(_tx_fn: object, rows: list[object], *_args: object) -> int:
    """execute_write stand-in that reports every row as created.

    write_decisions compares the created count with its input (T2.1), so mock
    sessions must return a count instead of a bare MagicMock.
    """
    return len(rows)


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

    # execute_write awaited twice: seed tx + stale-agent prune tx (v2)
    assert session.execute_write.await_count == 2
    # Extract the args passed to the FIRST call (the seeding tx)
    call_args = session.execute_write.call_args_list[0]
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
async def test_close_calls_driver_close(mock_driver: MagicMock) -> None:
    """close() calls driver.close()."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    await gsm.close()

    mock_driver.close.assert_awaited_once()


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
    session.execute_write.side_effect = _ack_rows
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
    session.execute_write.side_effect = _ack_rows
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
    session.execute_write.side_effect = _ack_rows
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
    tx.run.return_value.single = AsyncMock(return_value={"created": 2})
    decisions = [
        {
            "decision_id": "d1",
            "agent_id": "a1",
            "signal": "buy",
            "confidence": 0.5,
            "sentiment": 0.0,
            "rationale": "test",
            "cited_agents": [],
        },
        {
            "decision_id": "d2",
            "agent_id": "a2",
            "signal": "sell",
            "confidence": 0.6,
            "sentiment": -0.1,
            "rationale": "test",
            "cited_agents": [],
        },
    ]

    created = await GraphStateManager._batch_write_decisions_tx(tx, decisions, "cycle-1", 1)

    # Only 1 tx.run call (Decision creation, no CITED)
    assert tx.run.await_count == 1
    assert created == 2


@pytest.mark.asyncio()
async def test_batch_write_tx_creates_cited_when_present() -> None:
    """_batch_write_decisions_tx calls tx.run twice when cited_agents are non-empty."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    tx.run.return_value.single = AsyncMock(return_value={"created": 1})
    decisions = [
        {
            "decision_id": "d1",
            "agent_id": "a1",
            "signal": "buy",
            "confidence": 0.5,
            "sentiment": 0.0,
            "rationale": "test",
            "cited_agents": ["a2"],
        },
    ]

    await GraphStateManager._batch_write_decisions_tx(tx, decisions, "cycle-1", 1)

    # 2 tx.run calls (Decision creation + CITED creation)
    assert tx.run.await_count == 2


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

    await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph, num_rounds=3)

    session.execute_write.assert_awaited_once()


@pytest.mark.asyncio()
async def test_create_cycle_with_seed_event_returns_uuid(
    mock_driver: MagicMock,
    sample_seed_event_for_graph: SeedEvent,
) -> None:
    """create_cycle_with_seed_event returns a valid UUID4 string."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    cycle_id = await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph, num_rounds=3)

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
        await gsm.create_cycle_with_seed_event("test rumor", sample_seed_event_for_graph, num_rounds=3)

    assert exc_info.value.original_error is original_exc


@pytest.mark.asyncio()
async def test_create_cycle_with_entities_tx_skips_unwind_when_empty() -> None:
    """Transaction function skips Entity UNWIND when entities list is empty."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()

    await GraphStateManager._create_cycle_with_entities_tx(
        tx,
        "test-cycle-id",
        "test rumor",
        0.6,
        [],
        3,
    )

    # Only 1 tx.run call (Cycle creation, no Entity UNWIND)
    assert tx.run.await_count == 1


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
            {"source_id": "institutions_01", "target_id": "quants_01"},
            {"source_id": "macro_01", "target_id": "degens_01"},
            {"source_id": "institutions_01", "target_id": "degens_01"},
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
async def test_write_influence_edges_tx_empty_edges() -> None:
    """_write_influence_edges_tx with empty edges list does not call tx.run."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    await GraphStateManager._write_influence_edges_tx(tx, [], "cycle-1", 1)
    tx.run.assert_not_awaited()


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

    mock_driver.session.return_value.execute_write.side_effect = _ack_rows
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
    mock_driver.session.return_value.execute_write.side_effect = _ack_rows
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    result = await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1, decision_ids=pre_ids)

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
        await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1, decision_ids=wrong_ids)


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
# Phase 27: Shock analysis graph methods (Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_read_shock_event_returns_dict_when_exists(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — read_shock_event returns dict when ShockEvent exists for cycle."""
    from alphaswarm.graph import GraphStateManager

    expected = {
        "shock_id": "shock-uuid-1",
        "shock_text": "Fed emergency rate cut",
        "injected_before_round": 2,
        "created_at": "2026-04-11T12:00:00Z",
    }
    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=expected)

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    result = await gsm.read_shock_event("cycle-123")

    assert result == expected
    session.execute_read.assert_awaited_once()


@pytest.mark.asyncio()
async def test_read_shock_event_returns_none_when_no_shock(mock_driver: MagicMock) -> None:
    """Phase 27 SHOCK-04 — read_shock_event returns None when no ShockEvent exists."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=None)

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    result = await gsm.read_shock_event("cycle-no-shock")

    assert result is None


# ---------------------------------------------------------------------------
# Phase 28 Task 2 Tests: Replay read methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_read_full_cycle_signals(
    mock_driver: MagicMock,
    sample_personas_for_graph: list,
) -> None:
    """REPLAY-01 — read_full_cycle_signals returns dict keyed by (agent_id, round_num) -> AgentState."""
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.state import AgentState

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(
        return_value=[
            {"agent_id": "quants_01", "round_num": 1, "signal": "buy", "confidence": 0.9, "sentiment": 0.5},
            {"agent_id": "quants_01", "round_num": 2, "signal": "sell", "confidence": 0.6, "sentiment": -0.3},
            {"agent_id": "degens_01", "round_num": 1, "signal": "hold", "confidence": 0.4, "sentiment": 0.0},
        ]
    )

    gm = GraphStateManager(driver=mock_driver, personas=sample_personas_for_graph, database="neo4j")
    result = await gm.read_full_cycle_signals("test-cycle")

    assert isinstance(result, dict)
    assert result[("quants_01", 1)] == AgentState(signal=SignalType.BUY, confidence=0.9)
    assert result[("quants_01", 2)] == AgentState(signal=SignalType.SELL, confidence=0.6)
    assert result[("degens_01", 1)] == AgentState(signal=SignalType.HOLD, confidence=0.4)


@pytest.mark.asyncio()
async def test_read_completed_cycles(
    mock_driver: MagicMock,
    sample_personas_for_graph: list,
) -> None:
    """REPLAY-01 — read_completed_cycles returns list of cycle dicts."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(
        return_value=[
            {"cycle_id": "abc-123", "created_at": "2026-04-12T14:30:00", "seed_rumor": "Test rumor 1"},
            {"cycle_id": "def-456", "created_at": "2026-04-11T09:15:00", "seed_rumor": "Test rumor 2"},
        ]
    )

    gm = GraphStateManager(driver=mock_driver, personas=sample_personas_for_graph, database="neo4j")
    result = await gm.read_completed_cycles()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["cycle_id"] == "abc-123"


# ---------------------------------------------------------------------------
# Phase 35.1 — write_shock_event (B1 wiring fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_write_shock_event_creates_node_and_edge(mock_driver: MagicMock) -> None:
    """write_shock_event calls execute_write with (tx_fn, cycle_id, shock_id, shock_text, injected_before_round)."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    shock_id = await gsm.write_shock_event(
        cycle_id="c1",
        shock_text="Fed cut rates",
        injected_before_round=2,
    )

    session.execute_write.assert_awaited_once()
    call_args = session.execute_write.call_args
    # Positional args: (tx_func, cycle_id, shock_id, shock_text, injected_before_round)
    assert call_args[0][1] == "c1"
    assert call_args[0][2] == shock_id  # shock_id passed as the exact value returned
    assert call_args[0][3] == "Fed cut rates"
    assert call_args[0][4] == 2


@pytest.mark.asyncio()
async def test_write_shock_event_returns_uuid4(mock_driver: MagicMock) -> None:
    """write_shock_event returns a UUID4 string shock_id."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    shock_id = await gsm.write_shock_event(
        cycle_id="c1",
        shock_text="anything",
        injected_before_round=3,
    )

    # UUID4: 8-4-4-4-12 hex, 3rd group starts with 4, 4th group starts with 8/9/a/b
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.fullmatch(uuid4_pattern, shock_id) is not None, f"shock_id {shock_id!r} is not a valid UUID4"


@pytest.mark.asyncio()
async def test_write_shock_event_wraps_driver_errors(mock_driver: MagicMock) -> None:
    """Neo4jError from the driver is wrapped in Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write.side_effect = Neo4jError("boom")

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jWriteError, match="Failed to write shock_event for cycle c1"):
        await gsm.write_shock_event(
            cycle_id="c1",
            shock_text="anything",
            injected_before_round=2,
        )


def test_schema_includes_shock_id_unique_constraint() -> None:
    """SCHEMA_STATEMENTS contains a uniqueness constraint on (:ShockEvent).shock_id."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    pattern = r"CREATE CONSTRAINT shock_id_unique.*FOR \(se:ShockEvent\).*REQUIRE se\.shock_id IS UNIQUE"
    matches = [s for s in SCHEMA_STATEMENTS if re.search(pattern, s)]
    assert len(matches) == 1, f"Expected exactly one shock_id_unique constraint, found {len(matches)}: {matches!r}"


# ---------------------------------------------------------------------------
# T2.1: connectivity check and the decision write-count check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_verify_connectivity_delegates_to_the_driver(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    mock_driver.verify_connectivity = AsyncMock()
    await GraphStateManager(driver=mock_driver, personas=[]).verify_connectivity()
    mock_driver.verify_connectivity.assert_awaited_once()


@pytest.mark.asyncio()
async def test_verify_connectivity_propagates_driver_errors(mock_driver: MagicMock) -> None:
    from neo4j.exceptions import ServiceUnavailable

    from alphaswarm.graph import GraphStateManager

    mock_driver.verify_connectivity = AsyncMock(side_effect=ServiceUnavailable("down"))
    with pytest.raises(ServiceUnavailable):
        await GraphStateManager(driver=mock_driver, personas=[]).verify_connectivity()


@pytest.mark.asyncio()
async def test_write_decisions_raises_when_rows_are_dropped(
    mock_driver: MagicMock,
    sample_agent_decisions: list[tuple[str, AgentDecision]],
) -> None:
    """A MATCH that finds no Agent/Cycle silently drops rows; that must fail loudly."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write.side_effect = lambda _fn, rows, *_a: len(rows) - 1
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jWriteError, match=r"Wrote 2 of 3 decisions .* ensure_schema"):
        await gsm.write_decisions(sample_agent_decisions, "test-cycle-id", 1)


@pytest.mark.asyncio()
async def test_write_decisions_with_no_rows_writes_nothing_and_succeeds(
    mock_driver: MagicMock,
) -> None:
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write.side_effect = _ack_rows
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    assert await gsm.write_decisions([], "test-cycle-id", 1) == []


@pytest.mark.asyncio()
async def test_batch_write_tx_returns_the_cypher_created_count() -> None:
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    tx.run.return_value.single = AsyncMock(return_value={"created": 0})
    rows = [
        {
            "decision_id": "d1",
            "agent_id": "ghost",
            "signal": "buy",
            "confidence": 0.5,
            "sentiment": 0.0,
            "rationale": "x",
            "cited_agents": [],
        }
    ]

    assert await GraphStateManager._batch_write_decisions_tx(tx, rows, "cycle-1", 1) == 0
    assert "RETURN count(dec) AS created" in tx.run.await_args_list[0].args[0]


@pytest.mark.asyncio()
async def test_compute_influence_edges_skips_when_no_active_agents(mock_driver: MagicMock) -> None:
    """A fully failed round must not divide by zero (docs/DECISIONS.md#p8-d-01)."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=[{"source_id": "a", "target_id": "b"}])
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    assert await gsm.compute_influence_edges("c1", up_to_round=3, total_agents=0) == {}
    session.execute_read.assert_not_awaited()
    session.execute_write.assert_not_awaited()


async def test_create_cycle_rejects_non_positive_num_rounds() -> None:
    """num_rounds is validated before any database call."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(MagicMock(), [])
    with pytest.raises(ValueError, match="num_rounds"):
        await gsm.create_cycle_with_seed_event(
            "rumor",
            SeedEvent(raw_rumor="rumor", entities=[], overall_sentiment=0.0),
            num_rounds=0,
        )
