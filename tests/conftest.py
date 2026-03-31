"""Shared fixtures for AlphaSwarm tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from alphaswarm.config import AppSettings, GovernorSettings, generate_personas, load_bracket_configs
from alphaswarm.governor import ResourceGovernor
from alphaswarm.worker import WorkerPersonaConfig

if TYPE_CHECKING:
    from alphaswarm.types import AgentPersona, BracketConfig


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all ALPHASWARM_ environment variables."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def default_settings(monkeypatch: pytest.MonkeyPatch) -> AppSettings:
    """Return AppSettings with a clean environment (no .env influence)."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture()
def all_brackets() -> list[BracketConfig]:
    """Return default bracket configurations."""
    return load_bracket_configs()


@pytest.fixture()
def all_personas() -> list[AgentPersona]:
    """Return all 100 generated personas."""
    return generate_personas(load_bracket_configs())


# ---------------------------------------------------------------------------
# Phase 3: Resource governance fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_governor() -> ResourceGovernor:
    """ResourceGovernor with default GovernorSettings for unit testing.

    Uses default settings (baseline_parallel=8) with no state_store wiring.
    """
    return ResourceGovernor(GovernorSettings())


@pytest.fixture()
def sample_personas() -> list[WorkerPersonaConfig]:
    """4 WorkerPersonaConfig dicts for batch dispatch testing."""
    return [
        WorkerPersonaConfig(
            agent_id="quants_01",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="quants_02",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="degens_01",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
        WorkerPersonaConfig(
            agent_id="degens_02",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
    ]


# ---------------------------------------------------------------------------
# Phase 5: Seed event fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_seed_event():
    """Sample SeedEvent for testing seed injection pipeline."""
    from alphaswarm.types import EntityType, SeedEntity, SeedEvent

    return SeedEvent(
        raw_rumor="NVIDIA announces breakthrough in quantum computing",
        entities=[
            SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
            SeedEntity(name="Semiconductors", type=EntityType.SECTOR, relevance=0.7, sentiment=0.5),
        ],
        overall_sentiment=0.6,
    )


# ---------------------------------------------------------------------------
# Phase 4: Neo4j graph fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def neo4j_driver():
    """AsyncDriver connected to local Neo4j. Requires Docker running.

    Skips test if Neo4j is not available or auth fails.
    """
    import asyncio

    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import Neo4jError, ServiceUnavailable

    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", "alphaswarm"),
        max_connection_pool_size=5,
    )
    try:
        asyncio.get_event_loop().run_until_complete(driver.verify_connectivity())
    except (ServiceUnavailable, Neo4jError, OSError):
        pytest.skip("Neo4j not available (docker compose up -d)")
    yield driver
    asyncio.get_event_loop().run_until_complete(driver.close())


@pytest.fixture()
async def graph_manager(neo4j_driver, all_personas):
    """GraphStateManager with schema applied and agents seeded. Cleans up after test."""
    from alphaswarm.graph import GraphStateManager

    manager = GraphStateManager(
        driver=neo4j_driver,
        personas=all_personas,
        database="neo4j",
    )
    await manager.ensure_schema()
    yield manager
    # Clean all Decision, Cycle, Entity, and RationaleEpisode nodes between tests (keep Agent nodes)
    async with neo4j_driver.session(database="neo4j") as session:
        await session.run("MATCH (d:Decision) DETACH DELETE d")
        await session.run("MATCH (c:Cycle) DETACH DELETE c")
        await session.run("MATCH (e:Entity) DETACH DELETE e")
        await session.run("MATCH (re:RationaleEpisode) DETACH DELETE re")
