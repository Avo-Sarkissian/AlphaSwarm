"""Shared fixtures for AlphaSwarm tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from alphaswarm.config import AppSettings, GovernorSettings, generate_personas, load_bracket_configs
from alphaswarm.governor import ResourceGovernor
from alphaswarm.worker import WorkerPersonaConfig

if TYPE_CHECKING:
    from alphaswarm.types import AgentPersona, BracketConfig


# ---------------------------------------------------------------------------
# Hermetic environment (docs/DECISIONS.md#adr-tests-scoped-cleanup)
# ---------------------------------------------------------------------------

# Variables hermetic_env sets itself. Every env-clearing helper keeps them,
# otherwise AppSettings falls back to the operator's real .secrets/inference.json
# and Schwab/holdings.csv (relative to the repo root, where pytest runs).
HERMETIC_PRESERVED_ENV: Final[frozenset[str]] = frozenset(
    {"ALPHASWARM_INFERENCE_CONFIG_PATH", "ALPHASWARM_HOLDINGS_CSV_PATH"}
)


def clear_alphaswarm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete ALPHASWARM_* variables for one test, keeping HERMETIC_PRESERVED_ENV."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_") and key not in HERMETIC_PRESERVED_ENV:
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(scope="session", autouse=True)
def hermetic_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Isolate the whole session from the operator's machine.

    Removes every ALPHASWARM_* variable, stops AppSettings from reading .env,
    points the inference config at a temp file that does not exist yet (so
    load_inference_config returns the local defaults), and points the holdings
    CSV at a path that never exists (so no test can load the real portfolio).
    Yields the inference config path and restores everything on exit
    (docs/DECISIONS.md#adr-tests-scoped-cleanup).
    """
    saved_env = {k: v for k, v in os.environ.items() if k.startswith("ALPHASWARM_")}
    saved_env_file = AppSettings.model_config.get("env_file")
    for key in saved_env:
        del os.environ[key]
    hermetic_dir = tmp_path_factory.mktemp("hermetic")
    config_path = hermetic_dir / "inference.json"
    os.environ["ALPHASWARM_INFERENCE_CONFIG_PATH"] = str(config_path)
    os.environ["ALPHASWARM_HOLDINGS_CSV_PATH"] = str(hermetic_dir / "no-holdings.csv")
    AppSettings.model_config["env_file"] = None
    try:
        yield config_path
    finally:
        AppSettings.model_config["env_file"] = saved_env_file
        for key in [k for k in os.environ if k.startswith("ALPHASWARM_")]:
            del os.environ[key]
        os.environ.update(saved_env)


@pytest.fixture(autouse=True)
def _reset_hermetic_inference_config(hermetic_env: Path) -> Iterator[None]:
    """Delete the session's inference config after each test so a saved cloud
    config cannot change what later tests see."""
    yield
    hermetic_env.unlink(missing_ok=True)
    hermetic_env.with_name(f"{hermetic_env.name}.tmp").unlink(missing_ok=True)


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ALPHASWARM_* variables, keeping the hermetic paths."""
    clear_alphaswarm_env(monkeypatch)


@pytest.fixture()
def default_settings(monkeypatch: pytest.MonkeyPatch) -> AppSettings:
    """Return AppSettings with a clean environment (no .env influence)."""
    clear_alphaswarm_env(monkeypatch)
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
async def neo4j_driver():
    """AsyncDriver connected to local Neo4j. Requires Docker running.

    Skips test if Neo4j is not available or auth fails.

    The password comes from ALPHASWARM_NEO4J__PASSWORD when it is exported in
    the environment, falling back to the historical `alphaswarm` literal so
    installs created before the credential was made mandatory keep working.
    Note that `uv run` does not load `.env`: export the variable in your shell
    to run these tests against an instance with a per-install password.

    The destination stays the hardcoded loopback address on purpose — these
    tests write to whatever database they reach, so the target must not be
    steerable by the environment.

    Async-fixture form so verify_connectivity runs on the same event loop as
    the test that consumes the driver. The previous sync form used
    `asyncio.get_event_loop().run_until_complete(...)` which created futures
    on a different loop than pytest-asyncio's test loop, producing
    "got Future attached to a different loop" runtime errors.
    """
    import socket

    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

    # Cheap TCP-level preflight: avoids spinning up the AsyncDriver at all
    # when the port is closed (typical local dev where Neo4j isn't running).
    try:
        with socket.create_connection(("localhost", 7687), timeout=0.5):
            pass
    except OSError:
        pytest.skip("Neo4j not available (docker compose up -d)")

    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.environ.get("ALPHASWARM_NEO4J__PASSWORD", "alphaswarm")),
        max_connection_pool_size=5,
    )
    try:
        await driver.verify_connectivity()
    # AuthError is a Neo4jError subclass, so it must be caught first. Keeping
    # the two skips distinct stops "wrong password" from being misread as
    # "server is down" when the whole module silently skips.
    except AuthError:
        await driver.close()
        pytest.skip(
            "Neo4j rejected the test credential for user 'neo4j'. Export "
            "ALPHASWARM_NEO4J__PASSWORD with this instance's password "
            "(uv run does not read .env)."
        )
    except (ServiceUnavailable, Neo4jError, OSError):
        await driver.close()
        pytest.skip("Neo4j not available (docker compose up -d)")
    try:
        yield driver
    finally:
        await driver.close()


@pytest.fixture()
async def graph_manager(neo4j_driver, all_personas):
    """GraphStateManager with schema applied and agents seeded. Cleans up after test.

    DATA-SAFETY: tests share the live single-database Neo4j (Community edition
    has no second database). The previous cleanup ran unscoped DETACH DELETE
    over ALL Cycle/Decision/Post/Entity/RationaleEpisode nodes, destroying
    every real simulation cycle on the machine each time pytest ran. Cleanup
    is now scoped to cycles CREATED DURING THE TEST: cycle_ids present before
    the test are preserved, and only orphaned Entity nodes are removed.
    """
    from alphaswarm.graph import GraphStateManager

    manager = GraphStateManager(
        driver=neo4j_driver,
        personas=all_personas,
        database="neo4j",
    )
    await manager.ensure_schema()
    # Snapshot pre-existing cycles so real simulation data survives test runs.
    async with neo4j_driver.session(database="neo4j") as session:
        result = await session.run("MATCH (c:Cycle) RETURN collect(c.cycle_id) AS ids")
        record = await result.single()
        preexisting: list[str] = list(record["ids"]) if record else []
    yield manager
    # Delete ONLY data belonging to cycles created during this test
    # (keep Agent nodes; keep all pre-existing cycle data).
    async with neo4j_driver.session(database="neo4j") as session:
        await session.run(
            "MATCH (d:Decision) WHERE NOT d.cycle_id IN $keep DETACH DELETE d",
            keep=preexisting,
        )
        await session.run(
            "MATCH (p:Post) WHERE NOT p.cycle_id IN $keep DETACH DELETE p",
            keep=preexisting,
        )
        await session.run(
            "MATCH (re:RationaleEpisode) WHERE NOT re.cycle_id IN $keep DETACH DELETE re",
            keep=preexisting,
        )
        # INFLUENCED_BY edges connect Agent nodes, so DETACH DELETE on
        # decisions never removes them — without this they accumulate
        # forever (4k+ stale edges observed from past test runs).
        await session.run(
            "MATCH ()-[e:INFLUENCED_BY]->() WHERE NOT e.cycle_id IN $keep DELETE e",
            keep=preexisting,
        )
        await session.run(
            "MATCH (c:Cycle) WHERE NOT c.cycle_id IN $keep DETACH DELETE c",
            keep=preexisting,
        )
        # Entities are MERGE'd by name and shared across cycles: only remove
        # ones no longer referenced by any cycle.
        await session.run(
            "MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e"
        )
