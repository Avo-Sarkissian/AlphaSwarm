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


async def test_close_calls_driver_close(mock_driver: MagicMock) -> None:
    """close() calls driver.close()."""
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    await gsm.close()

    mock_driver.close.assert_awaited_once()


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
        None,
        None,
    )

    # Only 1 tx.run call (Cycle creation, no Entity UNWIND)
    assert tx.run.await_count == 1


# ---------------------------------------------------------------------------
# Phase 8: Influence edge computation tests
# ---------------------------------------------------------------------------


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


async def test_compute_influence_edges_zero_citations(mock_driver: MagicMock) -> None:
    """compute_influence_edges with zero citations returns empty dict and skips write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=[])
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    weights = await gsm.compute_influence_edges("cycle-1", 1, 10)
    assert weights == {}
    session.execute_write.assert_not_awaited()


async def test_write_influence_edges_tx_empty_edges() -> None:
    """_write_influence_edges_tx with empty edges list does not call tx.run."""
    from alphaswarm.graph import GraphStateManager

    tx = AsyncMock()
    await GraphStateManager._write_influence_edges_tx(tx, [], "cycle-1", 1)
    tx.run.assert_not_awaited()


# ---------------------------------------------------------------------------
# Narrative storage and legacy cleanup
# ---------------------------------------------------------------------------


async def test_ensure_schema_runs_legacy_property_cleanup(mock_driver: MagicMock) -> None:
    """ensure_schema removes retired properties through a managed write."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with patch.object(gsm, "seed_agents", new_callable=AsyncMock):
        await gsm.ensure_schema()

    write_fns = [c.args[0] for c in session.execute_write.await_args_list]
    assert GraphStateManager._legacy_property_cleanup_tx in write_fns


async def test_legacy_property_cleanup_tx_runs_each_statement() -> None:
    from alphaswarm.graph import LEGACY_PROPERTY_CLEANUP, GraphStateManager

    tx = AsyncMock()
    await GraphStateManager._legacy_property_cleanup_tx(tx)

    assert [c.args[0] for c in tx.run.await_args_list] == list(LEGACY_PROPERTY_CLEANUP)
    assert any("REMOVE a.decision_narrative" in stmt for stmt in LEGACY_PROPERTY_CLEANUP)


async def test_write_decision_narrative_without_target_is_a_no_op(mock_driver: MagicMock) -> None:
    """A narrative for an agent with no decision in the cycle writes nothing and does not raise."""
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write.return_value = 0
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.write_decision_narrative("c1", "degens_09", "orphan")

    session.execute_write.assert_awaited_once()
    assert session.execute_write.await_args.args[1:] == ("c1", "degens_09", "orphan")


def test_schema_statements_includes_episode_index() -> None:
    """SCHEMA_STATEMENTS contains RationaleEpisode composite index."""
    from alphaswarm.graph import SCHEMA_STATEMENTS

    episode_indexes = [s for s in SCHEMA_STATEMENTS if "episode_cycle_round" in s]
    assert len(episode_indexes) == 1
    assert "RationaleEpisode" in episode_indexes[0]


# ---------------------------------------------------------------------------
# RankedPost (peer-context formatting) and the Post schema index
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


# ---------------------------------------------------------------------------
# Phase 27: Shock analysis graph methods (Plan 01)
# ---------------------------------------------------------------------------


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


async def test_write_shock_event_wraps_driver_errors(mock_driver: MagicMock) -> None:
    """Neo4jError from the driver is wrapped in Neo4jWriteError."""
    from neo4j.exceptions import Neo4jError

    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write.side_effect = Neo4jError("boom")

    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jWriteError, match="write_shock_event"):
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
# Connectivity check and influence-edge guards
# ---------------------------------------------------------------------------


async def test_verify_connectivity_delegates_to_the_driver(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    mock_driver.verify_connectivity = AsyncMock()
    await GraphStateManager(driver=mock_driver, personas=[]).verify_connectivity()
    mock_driver.verify_connectivity.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# Error mapping, _read/_write helpers, query timeouts (docs/DECISIONS.md#p4-d-07)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc_factory", "write", "expected"),
    [
        ("service_unavailable", False, "Neo4jUnavailableError"),
        ("session_expired", True, "Neo4jUnavailableError"),
        ("auth", False, "Neo4jUnavailableError"),
        ("pool_timeout", True, "Neo4jUnavailableError"),
        ("syntax", False, "Neo4jQueryError"),
        ("syntax", True, "Neo4jWriteError"),
    ],
)
def test_map_graph_error(exc_factory: str, write: bool, expected: str) -> None:
    from neo4j.exceptions import AuthError as Neo4jAuthError
    from neo4j.exceptions import ClientError, ServiceUnavailable, SessionExpired

    from alphaswarm.graph import _map_graph_error

    original = {
        "service_unavailable": ServiceUnavailable("Couldn't connect to 127.0.0.1:7688"),
        "session_expired": SessionExpired("session expired"),
        "auth": Neo4jAuthError("The client is unauthorized due to authentication failure."),
        "pool_timeout": ClientError("failed to obtain a connection from the pool within 10.0s (timeout)"),
        "syntax": ClientError("Invalid input 'MATC'"),
    }[exc_factory]
    mapped = _map_graph_error(original, op="probe", write=write)
    assert type(mapped).__name__ == expected
    assert mapped.op == "probe"
    assert mapped.original_error is original


async def test_read_maps_driver_errors(mock_driver: MagicMock) -> None:
    from neo4j.exceptions import ServiceUnavailable

    from alphaswarm.errors import Neo4jUnavailableError
    from alphaswarm.graph import GraphStateManager

    original = ServiceUnavailable("down")
    mock_driver.session.return_value.execute_read = AsyncMock(side_effect=original)
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    with pytest.raises(Neo4jUnavailableError) as exc_info:
        await gsm._read(AsyncMock(), "c1", op="probe_read")
    assert exc_info.value.op == "probe_read"
    assert exc_info.value.__cause__ is original


async def test_write_maps_server_errors(mock_driver: MagicMock) -> None:
    from neo4j.exceptions import Neo4jError

    from alphaswarm.errors import Neo4jWriteError
    from alphaswarm.graph import GraphStateManager

    mock_driver.session.return_value.execute_write = AsyncMock(side_effect=Neo4jError("boom"))
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(Neo4jWriteError):
        await gsm._write(AsyncMock(), op="probe_write")


async def test_helpers_apply_the_query_timeout(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value=7)
    gsm = GraphStateManager(driver=mock_driver, personas=[], query_timeout_s=2.5)

    async def _tx(tx: object, value: int) -> int:
        return value

    assert await gsm._read(_tx, 1, op="probe") == 7
    passed_fn = session.execute_read.await_args.args[0]
    assert passed_fn.timeout == 2.5
    assert session.execute_read.await_args.args[1:] == (1,)


async def test_no_timeout_passes_the_function_through(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write = AsyncMock(return_value=None)
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    async def _tx(tx: object) -> None:
        return None

    await gsm._write(_tx, op="probe")
    assert session.execute_write.await_args.args[0] is _tx


async def test_verify_connectivity_maps_to_unavailable(mock_driver: MagicMock) -> None:
    from neo4j.exceptions import ServiceUnavailable

    from alphaswarm.errors import Neo4jUnavailableError
    from alphaswarm.graph import GraphStateManager

    original = ServiceUnavailable("down")
    mock_driver.verify_connectivity = AsyncMock(side_effect=original)
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(Neo4jUnavailableError) as exc_info:
        await gsm.verify_connectivity()
    assert exc_info.value.op == "verify_connectivity"
    assert exc_info.value.original_error is original


async def test_ensure_schema_maps_driver_errors(mock_driver: MagicMock) -> None:
    from neo4j.exceptions import ServiceUnavailable

    from alphaswarm.errors import Neo4jUnavailableError
    from alphaswarm.graph import GraphStateManager

    mock_driver.session.return_value.run = AsyncMock(side_effect=ServiceUnavailable("down"))
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(Neo4jUnavailableError) as exc_info:
        await gsm.ensure_schema()
    assert exc_info.value.op == "ensure_schema"


async def test_read_cycle_entities_returns_entity_refs(mock_driver: MagicMock) -> None:
    from alphaswarm.episodes import EntityRef
    from alphaswarm.graph import GraphStateManager

    refs = [EntityRef("ZZZT Holdings", "company")]
    mock_driver.session.return_value.execute_read = AsyncMock(return_value=refs)
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    assert await gsm.read_cycle_entities("cycle-abc") == refs


async def test_read_cycle_entities_tx_reads_name_and_type() -> None:
    from alphaswarm.episodes import EntityRef
    from alphaswarm.graph import GraphStateManager

    result = MagicMock()
    result.__aiter__.return_value = [
        {"name": "QQQX Robotics", "type": "company"},
        {"name": "Industrial Automation", "type": "sector"},
    ]
    tx = MagicMock()
    tx.run = AsyncMock(return_value=result)

    rows = await GraphStateManager._read_cycle_entities_tx(tx, "cycle-abc")
    assert rows == [
        EntityRef("QQQX Robotics", "company"),
        EntityRef("Industrial Automation", "sector"),
    ]
    cypher = tx.run.await_args.args[0]
    assert "(c:Cycle {cycle_id: $cycle_id})-[:MENTIONS]->(e:Entity)" in cypher


# ---------------------------------------------------------------------------
# Cycle status lifecycle (docs/DECISIONS.md#adr-cycle-metrics)
# ---------------------------------------------------------------------------


def test_schema_has_cycle_status_index() -> None:
    from alphaswarm.graph import SCHEMA_STATEMENTS

    assert "CREATE INDEX cycle_status IF NOT EXISTS FOR (c:Cycle) ON (c.status)" in SCHEMA_STATEMENTS


async def test_new_cycle_is_created_running() -> None:
    from alphaswarm.graph import GraphStateManager

    tx = MagicMock()
    tx.run = AsyncMock()
    await GraphStateManager._create_cycle_with_entities_tx(tx, "c1", "rumor", 0.4, [], 3, None, None)
    assert "status: 'running'" in tx.run.await_args_list[0].args[0]


async def test_set_cycle_status_unknown_cycle_raises(mock_driver: MagicMock) -> None:
    from alphaswarm.errors import Neo4jWriteError
    from alphaswarm.graph import GraphStateManager

    mock_driver.session.return_value.execute_write = AsyncMock(return_value=False)
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(Neo4jWriteError) as exc_info:
        await gsm.set_cycle_status("c-missing", "complete")
    assert exc_info.value.op == "set_cycle_status"


async def test_set_cycle_status_stores_the_error_code_with_failed(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_write = AsyncMock(return_value=True)
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    await gsm.set_cycle_status("c1", "failed", error_code="round_failed")
    assert session.execute_write.await_args.args[1:] == ("c1", "failed", "round_failed")
    await gsm.set_cycle_status("c1", "complete")
    assert session.execute_write.await_args.args[1:] == ("c1", "complete", None)


@pytest.mark.parametrize("status", ["running", "complete", "cancelled"])
async def test_set_cycle_status_rejects_an_error_code_without_failed(mock_driver: MagicMock, status: str) -> None:
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    with pytest.raises(ValueError, match="error_code"):
        await gsm.set_cycle_status("c1", status, error_code="round_failed")
    mock_driver.session.assert_not_called()


async def test_read_latest_cycle_id_passes_statuses(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    session = mock_driver.session.return_value
    session.execute_read = AsyncMock(return_value="c9")
    gsm = GraphStateManager(driver=mock_driver, personas=[])

    assert await gsm.read_latest_cycle_id() == "c9"
    assert session.execute_read.await_args.args[1] == ["complete"]
    await gsm.read_latest_cycle_id(statuses=("running", "complete"))
    assert session.execute_read.await_args.args[1] == ["running", "complete"]
    with pytest.raises(ValueError):
        await gsm.read_latest_cycle_id(statuses=())


# ---------------------------------------------------------------------------
# persist_round: one transaction per round (docs/DECISIONS.md#p4-d-08)
# ---------------------------------------------------------------------------


def _single(value: dict[str, object]) -> MagicMock:
    result = MagicMock()
    result.single = AsyncMock(return_value=value)
    return result


def _rows(rows: list[dict[str, object]]) -> MagicMock:
    result = MagicMock()
    result.__aiter__.return_value = rows
    return result


_DECISION_ROW = {
    "decision_id": "d1",
    "agent_id": "quants_01",
    "signal": "parse_error",
    "confidence": 0.0,
    "sentiment": 0.0,
    "rationale": "Inference failed",
    "error_kind": "inference",
    "control": False,
}


async def test_persist_round_tx_raises_on_decision_shortfall() -> None:
    from alphaswarm.graph import GraphStateManager

    tx = MagicMock()
    tx.run = AsyncMock(return_value=_single({"created": 1}))
    second = {**_DECISION_ROW, "decision_id": "d2", "agent_id": "ghost_99"}
    with pytest.raises(Neo4jWriteError) as exc_info:
        await GraphStateManager._persist_round_tx(tx, "c1", 1, [_DECISION_ROW, second], [], [], [])
    assert exc_info.value.op == "persist_round"
    assert tx.run.await_count == 1


async def test_persist_round_tx_raises_on_episode_shortfall() -> None:
    from alphaswarm.graph import GraphStateManager

    tx = MagicMock()
    tx.run = AsyncMock(side_effect=[_single({"created": 1}), _single({"n": 0})])
    episode = {
        "decision_id": "d1",
        "rationale": "r",
        "peer_context_received": "",
        "flip_type": "none",
        "round_num": 1,
        "cycle_id": "c1",
    }
    with pytest.raises(Neo4jWriteError) as exc_info:
        await GraphStateManager._persist_round_tx(tx, "c1", 1, [_DECISION_ROW], [], [episode], [])
    assert exc_info.value.op == "persist_round"


async def test_persist_round_tx_counts_dropped_citations() -> None:
    from alphaswarm.graph import GraphStateManager, PersistRoundResult

    tx = MagicMock()
    tx.run = AsyncMock(
        side_effect=[
            _single({"created": 1}),
            _rows([{"cited_id": "quants_02", "written": True}, {"cited_id": "ghost_99", "written": False}]),
            _single({"n": 1}),
            _single({"n": 2}),
        ]
    )
    summary, dropped = await GraphStateManager._persist_round_tx(
        tx,
        "c1",
        2,
        [_DECISION_ROW],
        [{"decision_id": "d1", "cited_id": "quants_02"}, {"decision_id": "d1", "cited_id": "ghost_99"}],
        [
            {
                "decision_id": "d1",
                "rationale": "r",
                "peer_context_received": "",
                "flip_type": "none",
                "round_num": 2,
                "cycle_id": "c1",
            }
        ],
        [{"decision_id": "d1", "entity_name": "ZZZT Holdings", "entity_type": "company", "match_type": "token"}],
    )
    assert summary == PersistRoundResult(
        decision_ids=("d1",),
        decisions_written=1,
        episodes_written=1,
        citations_written=1,
        citations_dropped=1,
        references_written=2,
    )
    assert dropped == ("ghost_99",)
    assert tx.run.await_args_list[0].kwargs["decisions"][0]["error_kind"] == "inference"


async def test_persist_round_rejects_misaligned_ids(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager

    gsm = GraphStateManager(driver=mock_driver, personas=[])
    decisions = [("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.6))]
    with pytest.raises(ValueError):
        await gsm.persist_round("c1", 1, decisions, decision_ids=[], episodes=[], entity_matches=[])


async def test_persist_round_sends_one_write_with_all_rows(mock_driver: MagicMock) -> None:
    from alphaswarm.episodes import EntityMatch, EpisodeRecord
    from alphaswarm.graph import GraphStateManager, PersistRoundResult

    session = mock_driver.session.return_value
    expected = PersistRoundResult(("d1",), 1, 1, 1, 0, 1)
    session.execute_write = AsyncMock(return_value=(expected, ()))
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    decisions = [
        (
            "quants_01",
            AgentDecision(signal=SignalType.BUY, confidence=0.6, rationale="ZZZT", cited_agents=["degens_01"]),
        )
    ]
    episode = EpisodeRecord("d1", "quants_01", "ZZZT", "", "none", 1, "c1")
    match = EntityMatch("d1", "ZZZT Holdings", "company", "substring")

    result = await gsm.persist_round(
        "c1",
        1,
        decisions,
        decision_ids=["d1"],
        episodes=[episode],
        entity_matches=[match],
    )
    assert result == expected
    session.execute_write.assert_awaited_once()
    _, cycle_id, round_num, decision_rows, cited_rows, episode_rows, reference_rows = (
        session.execute_write.await_args.args
    )
    assert (cycle_id, round_num) == ("c1", 1)
    assert decision_rows[0]["error_kind"] is None and decision_rows[0]["signal"] == "buy"
    assert decision_rows[0]["control"] is False
    assert cited_rows == [{"decision_id": "d1", "cited_id": "degens_01"}]
    assert episode_rows[0]["round_num"] == 1
    assert reference_rows == [
        {"decision_id": "d1", "entity_name": "ZZZT Holdings", "entity_type": "company", "match_type": "substring"}
    ]


async def test_persist_round_marks_only_control_ids_as_control(mock_driver: MagicMock) -> None:
    from alphaswarm.graph import GraphStateManager, PersistRoundResult

    session = mock_driver.session.return_value
    session.execute_write = AsyncMock(return_value=(PersistRoundResult(("d1", "d2"), 2, 0, 0, 0, 0), ()))
    gsm = GraphStateManager(driver=mock_driver, personas=[])
    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.6)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.5)),
    ]

    await gsm.persist_round(
        "c1", 2, decisions, decision_ids=["d1", "d2"], episodes=[], entity_matches=[], control_ids={"degens_01"}
    )
    decision_rows = session.execute_write.await_args.args[3]
    assert [(r["agent_id"], r["control"]) for r in decision_rows] == [("quants_01", False), ("degens_01", True)]


def test_post_writer_is_gone() -> None:
    """Post nodes are no longer written; RankedPost stays for peer formatting."""
    from alphaswarm.graph import GraphStateManager, RankedPost

    assert not hasattr(GraphStateManager, "write_posts")
    assert RankedPost.__dataclass_fields__.keys() >= {"agent_id", "content"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("{not json", None),
        ('["quants"]', None),
        (
            '{"quants": "fictional catalyst watcher", "legacy_suits": "x", "degens": 3}',
            {BracketType.QUANTS: "fictional catalyst watcher"},
        ),
    ],
)
def test_decode_modifiers_drops_bad_json_and_unknown_brackets(
    raw: object,
    expected: dict[BracketType, str] | None,
) -> None:
    from alphaswarm.graph import _decode_modifiers, _encode_modifiers

    assert _decode_modifiers(raw) == expected
    modifiers = {BracketType.QUANTS: "a", BracketType.DEGENS: "b"}
    assert _decode_modifiers(_encode_modifiers(modifiers)) == modifiers
