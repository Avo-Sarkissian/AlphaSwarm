"""Shared fixtures for AlphaSwarm tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn
from urllib.parse import urlsplit

import pytest
import pytest_asyncio

from alphaswarm.config import AppSettings, GovernorSettings, generate_personas, load_bracket_configs
from alphaswarm.governor import ResourceGovernor
from alphaswarm.worker import WorkerPersonaConfig
from tests.support.markers import RUN_LIVE_OPTION, apply_marker_policy

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentPersona, BracketConfig
    from tests.support.seed_builder import SeededCycle


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
# Neo4j: throwaway neo4j-test database only
# ---------------------------------------------------------------------------
# Hard-coded on purpose: the target must never be steerable by the environment
# (docs/DECISIONS.md#adr-tests-scoped-cleanup). Start it with scripts/neo4j_test.sh up.

NEO4J_TEST_URI: Final[str] = "bolt://127.0.0.1:7688"
NEO4J_TEST_AUTH: Final[tuple[str, str]] = ("neo4j", "alphaswarm-test-only")
NEO4J_TEST_DATABASE: Final[str] = "neo4j"
FORBIDDEN_NEO4J_PORT: Final[int] = 7687
# Cycle ids that graph_manager_test teardown must keep (session-scoped seeded cycles).
NEO4J_PROTECTED_CYCLES: set[str] = set()

_GUARD_EXIT_CODE: Final[int] = 3

# Same scoped cleanup the old live-database fixture used, plus ShockEvents.
_SCOPED_CLEANUP: Final[tuple[str, ...]] = (
    "MATCH (d:Decision) WHERE NOT d.cycle_id IN $keep DETACH DELETE d",
    "MATCH (p:Post) WHERE NOT p.cycle_id IN $keep DETACH DELETE p",
    "MATCH (re:RationaleEpisode) WHERE NOT re.cycle_id IN $keep DETACH DELETE re",
    "MATCH ()-[e:INFLUENCED_BY]->() WHERE NOT e.cycle_id IN $keep DELETE e",
    "MATCH (c:Cycle)-[:HAS_SHOCK]->(se:ShockEvent) WHERE NOT c.cycle_id IN $keep DETACH DELETE se",
    "MATCH (c:Cycle) WHERE NOT c.cycle_id IN $keep DETACH DELETE c",
    "MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-neo4j",
        action="store_true",
        default=False,
        help="Fail, not skip, when neo4j-test (127.0.0.1:7688) is unreachable.",
    )
    parser.addoption(
        RUN_LIVE_OPTION,
        action="store_true",
        default=False,
        help="Run tests marked live_network or ollama (internet or local Ollama).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Sockets, the session loop for neo4j tests, and live skips follow markers only."""
    apply_marker_policy(items, run_live=bool(config.getoption(RUN_LIVE_OPTION)))


def _refuse_forbidden_port(uri: str) -> None:
    """Guard 1: never connect to the dev database's port, whatever the URI says."""
    port = urlsplit(uri).port or FORBIDDEN_NEO4J_PORT  # no port means bolt's default, 7687
    if port == FORBIDDEN_NEO4J_PORT:
        pytest.exit(
            f"Refusing to run Neo4j tests against {uri}: port {FORBIDDEN_NEO4J_PORT} is the "
            "dev database. Tests use neo4j-test on 127.0.0.1:7688.",
            returncode=_GUARD_EXIT_CODE,
        )


async def _refuse_nonempty_database(driver: AsyncDriver) -> None:
    """Guard 2: the tmpfs test database starts empty, so Cycle nodes mean it is not ours."""
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run("MATCH (c:Cycle) RETURN count(c) AS n")
        record = await result.single()
    cycles = int(record["n"]) if record is not None else 0
    if cycles > 0:
        pytest.exit(
            f"Refusing to run Neo4j tests: the database on {NEO4J_TEST_URI} already holds "
            f"{cycles} Cycle node(s), and neo4j-test must start empty. Recreate it with "
            "`scripts/neo4j_test.sh reset`, then re-run.",
            returncode=_GUARD_EXIT_CODE,
        )


async def _port_open(uri: str, timeout_s: float = 0.5) -> bool:
    parts = urlsplit(uri)
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(parts.hostname, parts.port), timeout=timeout_s)
    except (OSError, TimeoutError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


def _neo4j_unavailable(request: pytest.FixtureRequest, reason: str) -> NoReturn:
    if request.config.getoption("--require-neo4j"):
        pytest.fail(f"{reason} (--require-neo4j is set)", pytrace=False)
    pytest.skip(reason)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def neo4j_test_driver(request: pytest.FixtureRequest) -> AsyncIterator[AsyncDriver]:
    """Session driver for neo4j-test, after both refusal guards pass (C-TEST-04)."""
    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import AuthError as Neo4jAuthError
    from neo4j.exceptions import DriverError, Neo4jError

    _refuse_forbidden_port(NEO4J_TEST_URI)
    if not await _port_open(NEO4J_TEST_URI):
        _neo4j_unavailable(request, "neo4j-test is not running (scripts/neo4j_test.sh up)")
    driver = AsyncGraphDatabase.driver(NEO4J_TEST_URI, auth=NEO4J_TEST_AUTH, max_connection_pool_size=5)
    try:
        await driver.verify_connectivity()
        await _refuse_nonempty_database(driver)
    except Neo4jAuthError:
        await driver.close()
        pytest.exit(
            "The server on 127.0.0.1:7688 rejected the neo4j-test credential, so it is not "
            "the throwaway test database. Stop it, then run scripts/neo4j_test.sh up.",
            returncode=_GUARD_EXIT_CODE,
        )
    except (DriverError, Neo4jError, OSError) as exc:
        await driver.close()
        _neo4j_unavailable(request, f"neo4j-test is not ready: {exc}")
    except BaseException:
        await driver.close()
        raise
    try:
        yield driver
    finally:
        # The only unscoped delete in the suite: both guards proved this is the
        # empty throwaway database (docs/DECISIONS.md#adr-tests-scoped-cleanup).
        async with driver.session(database=NEO4J_TEST_DATABASE) as session:
            result = await session.run("MATCH (n) DETACH DELETE n")
            await result.consume()
        await driver.close()


@pytest_asyncio.fixture(loop_scope="session")
async def graph_manager_test(
    neo4j_test_driver: AsyncDriver, all_personas: list[AgentPersona]
) -> AsyncIterator[GraphStateManager]:
    """GraphStateManager on neo4j-test with the schema applied (C-TEST-05).

    Teardown deletes only cycles created during the test and never the ids in
    NEO4J_PROTECTED_CYCLES. Agent nodes stay for the next test.
    """
    from alphaswarm.graph import GraphStateManager

    manager = GraphStateManager(driver=neo4j_test_driver, personas=all_personas, database=NEO4J_TEST_DATABASE)
    await manager.ensure_schema()
    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run("MATCH (c:Cycle) RETURN collect(c.cycle_id) AS ids")
        record = await result.single()
    preexisting: list[str] = list(record["ids"]) if record else []
    yield manager
    keep = sorted(set(preexisting) | NEO4J_PROTECTED_CYCLES)
    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        for query in _SCOPED_CLEANUP:
            result = await session.run(query, keep=keep)
            await result.consume()


# ---------------------------------------------------------------------------
# Seeded cycle for read-model and report golden tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_cycle_2r(neo4j_test_driver: AsyncDriver) -> SeededCycle:
    """Two-round twin of `seeded_cycle`.

    Built before the 3-round cycle (see `seeded_cycle`), so every neo4j session
    holds the same two protected cycles and the 3-round one stays the newest.
    """
    from alphaswarm.graph import GraphStateManager
    from tests.support.seed_builder import build_seeded_cycle

    gm = GraphStateManager(
        driver=neo4j_test_driver,
        personas=generate_personas(load_bracket_configs()),
        database=NEO4J_TEST_DATABASE,
    )
    await gm.ensure_schema()
    seeded = await build_seeded_cycle(gm, num_rounds=2)
    NEO4J_PROTECTED_CYCLES.add(seeded.cycle_id)
    return seeded


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_cycle(neo4j_test_driver: AsyncDriver, seeded_cycle_2r: SeededCycle) -> SeededCycle:
    """Session-scoped 3-round cycle in neo4j-test, written through the real write API.

    Built once (deterministic content, see tests/support/seed_builder.py) and protected
    from graph_manager_test's function-scoped cleanup. neo4j_test_driver's session teardown
    wipes the throwaway database afterwards.
    """
    _ = seeded_cycle_2r  # build order: the 2-round twin first, so cycle listings are deterministic
    from alphaswarm.graph import GraphStateManager
    from tests.support.seed_builder import build_seeded_cycle

    gm = GraphStateManager(
        driver=neo4j_test_driver,
        personas=generate_personas(load_bracket_configs()),
        database=NEO4J_TEST_DATABASE,
    )
    await gm.ensure_schema()
    seeded = await build_seeded_cycle(gm, num_rounds=3)
    NEO4J_PROTECTED_CYCLES.add(seeded.cycle_id)
    return seeded


FIXED_GIT_SHA: Final = "0" * 40


@pytest.fixture(autouse=True)
def fixed_git_revision(monkeypatch: pytest.MonkeyPatch) -> tuple[str, bool]:
    """Pin the git state run_simulation stamps into cycle metrics.

    Keeps run_simulation tests and scenario goldens independent of the
    checkout's HEAD and dirty state, and keeps git subprocesses out of the
    suite. tests/test_manifest.py calls alphaswarm.manifest directly and is
    unaffected; a test may override the value with its own monkeypatch.
    """
    value = (FIXED_GIT_SHA, False)
    monkeypatch.setattr("alphaswarm.simulation.current_git_revision", lambda: value)
    return value


@pytest.fixture()
def instant_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with a recorder: delays are logged, no wall-clock wait.

    Libraries that call asyncio.sleep through the module attribute (backoff, the
    cloud providers' retry loops, the rate limiter) all see the recorder.
    """
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def _record(delay: float, result: Any = None) -> Any:
        delays.append(float(delay))
        return await real_sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return delays
