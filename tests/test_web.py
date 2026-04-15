"""Tests for AlphaSwarm web package: health endpoint, lifespan, SimulationManager, ConnectionManager, WebSocket state stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.simulation_manager import (
    NoSimulationRunningError,
    ShockAlreadyQueuedError,
    SimulationAlreadyRunningError,
    SimulationManager,
)
from alphaswarm.web.connection_manager import ConnectionManager


# ---------------------------------------------------------------------------
# Test helpers — lightweight lifespan that bypasses .env / Neo4j / Ollama
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Build a test-friendly FastAPI app with a clean-env lifespan.

    Uses AppSettings(_env_file=None) to avoid the .env file's extra keys
    that would fail Pydantic strict validation in unit tests.
    """
    from contextlib import asynccontextmanager
    from collections.abc import AsyncGenerator

    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.edges import router as edges_router
    from alphaswarm.web.routes.health import router as health_router
    from alphaswarm.web.routes.replay import router as replay_router
    from alphaswarm.web.routes.simulation import router as simulation_router
    from alphaswarm.web.routes.websocket import router as ws_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _unit_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Use _env_file=None to skip the .env file with extra keys
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        # with_ollama=False, with_neo4j=False for unit tests (no external services)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        sim_manager = SimulationManager(app_state, brackets)
        replay_manager = ReplayManager(app_state)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-Test", lifespan=_unit_lifespan)
    app.include_router(health_router, prefix="/api")
    app.include_router(simulation_router, prefix="/api")
    app.include_router(edges_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(ws_router)  # No prefix — /ws/state is the full path
    return app


# ---------------------------------------------------------------------------
# Test 1: Health endpoint returns 200 with correct JSON (BE-01)
# ---------------------------------------------------------------------------


def test_health_endpoint() -> None:
    """GET /api/health returns 200 with all required fields."""
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "simulation_phase" in data
        assert "memory_percent" in data
        assert "is_simulation_running" in data
        assert data["status"] == "ok"
        assert isinstance(data["simulation_phase"], str)
        assert isinstance(data["memory_percent"], float)
        assert data["is_simulation_running"] is False


# ---------------------------------------------------------------------------
# Test 2: Lifespan creates all objects inside event loop (BE-01)
# ---------------------------------------------------------------------------


def test_lifespan_creates_objects_inside_loop() -> None:
    """TestClient lifespan creates app_state, sim_manager, connection_manager on app.state."""
    with TestClient(_make_test_app()) as client:
        assert client.app.state.app_state is not None
        assert client.app.state.sim_manager is not None
        assert client.app.state.connection_manager is not None
        assert client.app.state.app_state.state_store is not None
        assert client.app.state.app_state.governor is not None


# ---------------------------------------------------------------------------
# Test 3: SimulationManager 409 guard (SC-4)
# ---------------------------------------------------------------------------


async def test_simulation_manager_409_guard() -> None:
    """Concurrent start() raises SimulationAlreadyRunningError."""
    from unittest.mock import MagicMock

    mock_app_state = MagicMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    # Hold the lock to simulate a running simulation
    await sm._lock.acquire()
    sm._is_running = True

    with pytest.raises(SimulationAlreadyRunningError):
        await sm.start("second seed")

    sm._lock.release()


# ---------------------------------------------------------------------------
# Test 4: ConnectionManager per-client queue isolation (BE-03)
# ---------------------------------------------------------------------------


async def test_websocket_queue_isolation() -> None:
    """Each client has its own queue — draining one does not affect the other."""
    from unittest.mock import AsyncMock

    cm = ConnectionManager()
    q1: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    q2: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    cm._clients[ws1] = q1
    cm._clients[ws2] = q2

    cm.broadcast("snapshot_data")

    # Both queues received the message
    assert q1.qsize() == 1
    assert q2.qsize() == 1

    # Drain q1 — q2 unaffected
    _ = q1.get_nowait()
    assert q1.qsize() == 0
    assert q2.qsize() == 1


# ---------------------------------------------------------------------------
# Test 5: ConnectionManager drop-oldest on overflow (BE-03)
# ---------------------------------------------------------------------------


async def test_connection_manager_drop_oldest() -> None:
    """When queue is full (100), broadcast drops oldest and puts newest."""
    from unittest.mock import AsyncMock

    cm = ConnectionManager()
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    ws = AsyncMock()
    cm._clients[ws] = queue

    # Fill queue to capacity
    for i in range(100):
        queue.put_nowait(f"msg_{i}")
    assert queue.qsize() == 100

    # Broadcast one more — should drop oldest (msg_0), add newest
    cm.broadcast("newest")
    assert queue.qsize() == 100

    # Drain all and verify newest is present and msg_0 is gone
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert "newest" in items
    assert "msg_0" not in items


# ---------------------------------------------------------------------------
# Test 6: ConnectionManager disconnect cancels writer task (BE-03)
# ---------------------------------------------------------------------------


async def test_connection_manager_disconnect_cancels_task() -> None:
    """disconnect() cancels the writer task for the client."""
    from unittest.mock import AsyncMock

    cm = ConnectionManager()
    ws = AsyncMock()
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    cm._clients[ws] = queue

    # Create a real task that blocks on queue.get()
    async def fake_writer() -> None:
        await queue.get()  # Will block forever — needs cancellation

    task = asyncio.create_task(fake_writer())
    cm._tasks[ws] = task

    await cm.disconnect(ws)

    assert task.cancelled() or task.done()
    assert ws not in cm._clients
    assert ws not in cm._tasks


# ---------------------------------------------------------------------------
# Test 7: POST /api/simulate/start returns 409 when simulation is running (SC-4)
# ---------------------------------------------------------------------------


def test_simulate_start_409_when_running() -> None:
    """POST /api/simulate/start returns HTTP 409 when simulation is already running."""
    from unittest.mock import AsyncMock, patch
    from alphaswarm.web.simulation_manager import SimulationAlreadyRunningError

    with TestClient(_make_test_app()) as client:
        with patch.object(
            client.app.state.sim_manager,
            "start",
            new=AsyncMock(side_effect=SimulationAlreadyRunningError("Simulation already running")),
        ):
            r = client.post("/api/simulate/start", json={"seed": "test seed"})
            assert r.status_code == 409
            data = r.json()
            assert "detail" in data
            assert data["detail"]["error"] == "simulation_already_running"


# ---------------------------------------------------------------------------
# Phase 30: WebSocket State Stream test helpers
# ---------------------------------------------------------------------------


def _make_ws_test_app() -> FastAPI:
    """FastAPI test app for WebSocket tests. Starts broadcaster (unlike _unit_lifespan)."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncGenerator

    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.broadcaster import start_broadcaster
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.routes.websocket import router as ws_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _ws_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        sim_manager = SimulationManager(app_state, brackets)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.connection_manager = connection_manager

        # Start broadcaster — needed for WebSocket tests
        broadcaster_task = start_broadcaster(app_state.state_store, connection_manager)
        app.state.broadcaster_task = broadcaster_task

        yield

        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-WS-Test", lifespan=_ws_lifespan)
    app.include_router(ws_router)  # No prefix — /ws/state is the full path
    return app


# ---------------------------------------------------------------------------
# Phase 30: WebSocket State Stream tests (BE-04)
# ---------------------------------------------------------------------------


def test_snapshot_to_json() -> None:
    """snapshot_to_json returns valid JSON with all required fields."""
    import json

    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    store = StateStore()
    raw = snapshot_to_json(store)
    parsed = json.loads(raw)
    assert "phase" in parsed
    assert "agent_states" in parsed
    assert "bracket_summaries" in parsed
    assert "rationale_entries" in parsed
    assert "governor_metrics" in parsed
    # rationale_entries must be a list (not string or None)
    assert isinstance(parsed["rationale_entries"], list)


def test_broadcaster_cancellation() -> None:
    """start_broadcaster returns a cancellable asyncio.Task."""
    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import start_broadcaster

    async def _run() -> None:
        store = StateStore()
        cm = ConnectionManager()
        task = start_broadcaster(store, cm)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()

    asyncio.get_event_loop().run_until_complete(_run())


def test_ws_state_receives_snapshot() -> None:
    """Connecting to /ws/state receives JSON when broadcaster sends."""
    import json

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/state") as ws:
            # Seed a broadcast directly via app state — no 200ms tick dependency
            client.app.state.connection_manager.broadcast(
                json.dumps({"phase": "idle", "agent_states": {}, "rationale_entries": []})
            )
            data = ws.receive_text()
            parsed = json.loads(data)
            assert "phase" in parsed
            assert "agent_states" in parsed
            assert "rationale_entries" in parsed


def test_ws_state_disconnect_cleanup() -> None:
    """Client count drops to 0 after WebSocket disconnect."""
    app = _make_ws_test_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/state") as ws:
            assert client.app.state.connection_manager.client_count == 1
        # After exiting context manager, disconnect should have fired
        assert client.app.state.connection_manager.client_count == 0


def test_ws_state_same_connection_manager() -> None:
    """Broadcaster and /ws/state endpoint share the same connection_manager object."""
    import json

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/state") as ws:
            # Broadcasting via app.state.connection_manager should reach the WS client
            # This proves the route handler and lifespan use the same object
            cm = client.app.state.connection_manager
            cm.broadcast(json.dumps({"phase": "identity_check"}))
            data = ws.receive_text()
            parsed = json.loads(data)
            assert parsed["phase"] == "identity_check"


# ---------------------------------------------------------------------------
# Test 13: create_app() production path registers /ws/state (BE-04)
# ---------------------------------------------------------------------------


def test_create_app_ws_route_registered() -> None:
    """Production create_app() registers /ws/state -- catches wiring drift from _make_test_app."""
    from alphaswarm.web.app import create_app as production_create_app

    # Inspect registered routes on the production app before lifespan starts.
    # This catches the case where ws_router is missing from create_app() even though
    # _make_test_app() includes it. Does NOT start lifespan (no Ollama/Neo4j needed).
    prod_app = production_create_app()
    route_paths = [getattr(r, "path", None) for r in prod_app.routes]
    assert "/ws/state" in route_paths, (
        f"/ws/state not registered in production create_app(). "
        f"Found routes: {route_paths}"
    )


# ---------------------------------------------------------------------------
# Phase 31: Edges endpoint tests (VIS-03)
# ---------------------------------------------------------------------------


def test_edges_endpoint_503_without_neo4j() -> None:
    """GET /api/edges/{cycle_id}?round=1 returns 503 when graph_manager is None."""
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/edges/test-cycle?round=1")
        assert r.status_code == 503
        data = r.json()
        assert data["detail"]["error"] == "graph_unavailable"


def test_edges_endpoint_requires_round_param() -> None:
    """GET /api/edges/{cycle_id} without round query param returns 422."""
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/edges/test-cycle")
        assert r.status_code == 422


def test_edges_endpoint_round_validation() -> None:
    """GET /api/edges/{cycle_id}?round=0 returns 422 (round must be 1-3)."""
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/edges/test-cycle?round=0")
        assert r.status_code == 422
        r2 = client.get("/api/edges/test-cycle?round=4")
        assert r2.status_code == 422


def test_edges_route_registered_in_production_app() -> None:
    """Production create_app() registers /api/edges/{cycle_id} route."""
    from alphaswarm.web.app import create_app as production_create_app
    prod_app = production_create_app()
    route_paths = [getattr(r, "path", None) for r in prod_app.routes]
    assert "/api/edges/{cycle_id}" in route_paths, (
        f"/api/edges/{{cycle_id}} not registered. Found: {route_paths}"
    )


# ---------------------------------------------------------------------------
# Phase 32 Task 1: SimulationManager create_task + done-callback + stop + shock
# ---------------------------------------------------------------------------


async def test_sim_manager_init_accepts_brackets() -> None:
    """SimulationManager.__init__ accepts app_state and brackets; stores both."""
    from unittest.mock import MagicMock

    mock_app_state = MagicMock()
    brackets_list = [MagicMock(), MagicMock()]
    sm = SimulationManager(mock_app_state, brackets=brackets_list)
    assert sm._app_state is mock_app_state
    assert sm._brackets is brackets_list


async def test_sim_manager_start_creates_task() -> None:
    """start(seed) creates an asyncio.Task stored as self._task."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_app_state = MagicMock()
    mock_app_state.state_store = MagicMock()
    mock_app_state.state_store.set_phase = AsyncMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    # Mock _run so it completes immediately without needing real deps
    async def _fake_run(seed: str) -> None:
        pass

    with patch.object(sm, "_run", side_effect=_fake_run):
        await sm.start("test seed")
        # Task should exist right after start
        assert sm._task is not None
        assert sm._is_running is True

        # Wait for task to complete
        await asyncio.sleep(0.05)

        # After completion, done-callback should have reset state
        assert sm._is_running is False
        assert sm._task is None


async def test_sim_manager_done_callback_releases_lock_on_exception() -> None:
    """_on_task_done releases lock and resets _is_running even if task had exception."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_app_state = MagicMock()
    mock_app_state.state_store = MagicMock()
    mock_app_state.state_store.set_phase = AsyncMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    async def _failing_run(seed: str) -> None:
        raise RuntimeError("Simulation exploded")

    with patch.object(sm, "_run", side_effect=_failing_run):
        await sm.start("test seed")
        # Wait for task to complete and callback to fire
        await asyncio.sleep(0.05)

        assert sm._is_running is False
        assert sm._task is None
        assert not sm._lock.locked()  # Lock must be released


async def test_sim_manager_stop_cancels_task() -> None:
    """stop() calls self._task.cancel() when running; raises when not running."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_app_state = MagicMock()
    mock_app_state.state_store = MagicMock()
    mock_app_state.state_store.set_phase = AsyncMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    # stop() when not running should raise
    with pytest.raises(NoSimulationRunningError):
        sm.stop()

    # Start a long-running simulation
    async def _long_run(seed: str) -> None:
        await asyncio.sleep(100)

    with patch.object(sm, "_run", side_effect=_long_run):
        await sm.start("test seed")
        assert sm._is_running is True

        sm.stop()  # Should cancel the task

        # Wait for cancellation + callback
        await asyncio.sleep(0.05)

        assert sm._is_running is False
        assert sm._task is None
        assert not sm._lock.locked()


async def test_sim_manager_inject_shock() -> None:
    """inject_shock(text) stores _pending_shock when running; raises when not running."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_app_state = MagicMock()
    mock_app_state.state_store = MagicMock()
    mock_app_state.state_store.set_phase = AsyncMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    # inject_shock when not running should raise
    with pytest.raises(NoSimulationRunningError):
        sm.inject_shock("crash news")

    # Start a long-running simulation
    async def _long_run(seed: str) -> None:
        await asyncio.sleep(100)

    with patch.object(sm, "_run", side_effect=_long_run):
        await sm.start("test seed")

        sm.inject_shock("crash news")
        assert sm.pending_shock == "crash news"

        # Second inject should raise (concurrent guard)
        with pytest.raises(ShockAlreadyQueuedError):
            sm.inject_shock("another shock")

        # consume_shock returns and clears
        consumed = sm.consume_shock()
        assert consumed == "crash news"
        assert sm.pending_shock is None

        # Clean up
        sm.stop()
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Phase 32 Task 2: Stop and shock REST endpoints + cancellation phase reset
# ---------------------------------------------------------------------------


def test_simulate_start_202() -> None:
    """POST /api/simulate/start returns 202 with accepted status."""
    from unittest.mock import AsyncMock, patch

    with TestClient(_make_test_app()) as client:
        with patch.object(
            client.app.state.sim_manager,
            "start",
            new=AsyncMock(),
        ):
            r = client.post("/api/simulate/start", json={"seed": "test rumor"})
            assert r.status_code == 202
            data = r.json()
            assert data["status"] == "accepted"
            assert data["message"] == "Simulation started"


def test_simulate_stop_200_and_409() -> None:
    """POST /api/simulate/stop returns 200 when running, 409 when not."""
    from unittest.mock import MagicMock, patch
    from alphaswarm.web.simulation_manager import NoSimulationRunningError

    with TestClient(_make_test_app()) as client:
        # Happy path: stop succeeds
        with patch.object(
            client.app.state.sim_manager,
            "stop",
            new=MagicMock(),
        ):
            r = client.post("/api/simulate/stop")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "stopped"

        # Sad path: no simulation running
        with patch.object(
            client.app.state.sim_manager,
            "stop",
            new=MagicMock(side_effect=NoSimulationRunningError("No simulation is running")),
        ):
            r = client.post("/api/simulate/stop")
            assert r.status_code == 409
            data = r.json()
            assert data["detail"]["error"] == "no_simulation_running"


def test_simulate_shock_queued_and_409() -> None:
    """POST /api/simulate/shock returns 200 when queued, 409 when not running."""
    from unittest.mock import MagicMock, patch
    from alphaswarm.web.simulation_manager import NoSimulationRunningError

    with TestClient(_make_test_app()) as client:
        # Happy path: shock queued
        with patch.object(
            client.app.state.sim_manager,
            "inject_shock",
            new=MagicMock(),
        ):
            r = client.post("/api/simulate/shock", json={"shock_text": "market crash"})
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "queued"
            assert data["message"] == "Shock queued for next round"

        # Sad path: no simulation running
        with patch.object(
            client.app.state.sim_manager,
            "inject_shock",
            new=MagicMock(side_effect=NoSimulationRunningError("No simulation is running")),
        ):
            r = client.post("/api/simulate/shock", json={"shock_text": "crash"})
            assert r.status_code == 409
            data = r.json()
            assert data["detail"]["error"] == "no_simulation_running"


def test_simulate_shock_concurrent_409() -> None:
    """POST /api/simulate/shock returns 409 when shock already queued."""
    from unittest.mock import MagicMock, patch
    from alphaswarm.web.simulation_manager import ShockAlreadyQueuedError

    with TestClient(_make_test_app()) as client:
        with patch.object(
            client.app.state.sim_manager,
            "inject_shock",
            new=MagicMock(side_effect=ShockAlreadyQueuedError("A shock is already queued")),
        ):
            r = client.post("/api/simulate/shock", json={"shock_text": "another shock"})
            assert r.status_code == 409
            data = r.json()
            assert data["detail"]["error"] == "shock_already_queued"


async def test_sim_manager_cancellation_resets_phase_to_idle() -> None:
    """Cancelling a simulation resets StateStore.phase to IDLE."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from alphaswarm.types import SimulationPhase

    mock_app_state = MagicMock()
    mock_state_store = MagicMock()
    mock_state_store.set_phase = AsyncMock()
    mock_app_state.state_store = mock_state_store
    sm = SimulationManager(mock_app_state, brackets=[])

    async def _long_run(seed: str) -> None:
        await asyncio.sleep(100)

    with patch.object(sm, "_run", side_effect=_long_run):
        await sm.start("test seed")
        sm.stop()

        # Wait for cancellation + done-callback + reset task
        await asyncio.sleep(0.1)

        # Verify set_phase was called with IDLE
        mock_state_store.set_phase.assert_called_with(SimulationPhase.IDLE)


# ---------------------------------------------------------------------------
# Phase 32 Plan 02: Replay endpoints (BE-08, BE-09, BE-10)
# ---------------------------------------------------------------------------


def test_replay_cycles_503() -> None:
    """GET /api/replay/cycles returns 503 when graph_manager is None."""
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/replay/cycles")
        assert r.status_code == 503
        data = r.json()
        assert data["detail"]["error"] == "graph_unavailable"


def test_replay_start_503_without_neo4j() -> None:
    """POST /api/replay/start/{cycle_id} returns 503 when graph_manager is None."""
    with TestClient(_make_test_app()) as client:
        r = client.post("/api/replay/start/test-cycle-123")
        assert r.status_code == 503
        data = r.json()
        assert data["detail"]["error"] == "graph_unavailable"


def test_replay_advance_409_no_active_replay() -> None:
    """POST /api/replay/advance returns 409 when no replay is active."""
    with TestClient(_make_test_app()) as client:
        r = client.post("/api/replay/advance")
        assert r.status_code == 409
        data = r.json()
        assert data["detail"]["error"] == "no_replay_active"


def test_replay_routes_registered_in_production_app() -> None:
    """Production create_app() registers /api/replay/* routes."""
    from alphaswarm.web.app import create_app as production_create_app

    prod_app = production_create_app()
    route_paths = [getattr(r, "path", None) for r in prod_app.routes]
    assert "/api/replay/cycles" in route_paths
    assert "/api/replay/start/{cycle_id}" in route_paths
    assert "/api/replay/advance" in route_paths
    assert "/api/replay/stop" in route_paths


def test_edges_endpoint_regression_sc3() -> None:
    """GET /api/edges/{cycle_id}?round=N returns 503 without Neo4j (SC-3 regression).

    SC-3: GET /api/edges/{cycle_id}?round=N returns the INFLUENCED_BY edge list.
    This endpoint was implemented in Phase 31. This test verifies it is still
    registered and responds correctly after Phase 32 router additions.
    """
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/edges/test-cycle?round=1")
        assert r.status_code == 503  # graph_manager is None in test app
        data = r.json()
        assert data["detail"]["error"] == "graph_unavailable"


# ---------------------------------------------------------------------------
# Phase 34 Plan 01: Replay backend tests (D-07 through D-11)
# ---------------------------------------------------------------------------


def test_replay_start_real_logic() -> None:
    """POST /api/replay/start/{cycle_id} loads signals, sets round 1, returns 200."""
    from unittest.mock import AsyncMock

    from alphaswarm.state import AgentState
    from alphaswarm.types import SignalType

    app = _make_test_app()
    with TestClient(app) as client:
        # Access app_state and set mock graph_manager
        app_state = app.state.app_state
        mock_gm = AsyncMock()
        # read_full_cycle_signals returns dict[(agent_id, round), AgentState]
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={
            ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
            ("agent_1", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
            ("agent_1", 3): AgentState(signal=SignalType.HOLD, confidence=0.5),
        })
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app_state.graph_manager = mock_gm

        r = client.post("/api/replay/start/test-cycle-abc")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["cycle_id"] == "test-cycle-abc"
        assert data["round_num"] == 1
        assert app.state.replay_manager.is_active is True


def test_replay_start_409_already_active() -> None:
    """POST /api/replay/start returns 409 when replay already active."""
    from unittest.mock import AsyncMock

    from alphaswarm.state import AgentState
    from alphaswarm.types import SignalType

    app = _make_test_app()
    with TestClient(app) as client:
        app_state = app.state.app_state
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={
            ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
        })
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app_state.graph_manager = mock_gm

        r1 = client.post("/api/replay/start/cycle-1")
        assert r1.status_code == 200
        r2 = client.post("/api/replay/start/cycle-2")
        assert r2.status_code == 409
        assert r2.json()["detail"]["error"] == "replay_already_active"


def test_replay_start_404_cycle_not_found() -> None:
    """POST /api/replay/start returns 404 when cycle has no signals."""
    from unittest.mock import AsyncMock

    app = _make_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={})  # empty
        app.state.app_state.graph_manager = mock_gm

        r = client.post("/api/replay/start/nonexistent-cycle")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "cycle_not_found"


def test_replay_advance_real_logic() -> None:
    """POST /api/replay/advance increments round and returns new round_num."""
    from unittest.mock import AsyncMock

    from alphaswarm.state import AgentState
    from alphaswarm.types import SignalType

    app = _make_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={
            ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
            ("agent_1", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
            ("agent_1", 3): AgentState(signal=SignalType.HOLD, confidence=0.5),
        })
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app.state.app_state.graph_manager = mock_gm

        client.post("/api/replay/start/test-cycle-abc")
        r = client.post("/api/replay/advance")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["round_num"] == 2


def test_replay_stop_resets_phase() -> None:
    """POST /api/replay/stop resets replay_manager to inactive and phase to IDLE."""
    from unittest.mock import AsyncMock

    from alphaswarm.state import AgentState
    from alphaswarm.types import SignalType

    app = _make_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={
            ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
        })
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app.state.app_state.graph_manager = mock_gm

        client.post("/api/replay/start/test-cycle-abc")
        assert app.state.replay_manager.is_active is True
        r = client.post("/api/replay/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert app.state.replay_manager.is_active is False


def test_replay_stop_409_no_active_replay() -> None:
    """POST /api/replay/stop returns 409 when no replay is active."""
    with TestClient(_make_test_app()) as client:
        r = client.post("/api/replay/stop")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "no_replay_active"


def test_broadcaster_uses_replay_snapshot_when_active() -> None:
    """snapshot_to_json uses replay_manager.store.snapshot() when active."""
    import json
    from unittest.mock import MagicMock

    from alphaswarm.state import AgentState, ReplayStore, StateStore
    from alphaswarm.types import SignalType
    from alphaswarm.web.broadcaster import snapshot_to_json

    state_store = StateStore()
    signals = {("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8)}
    replay_store = ReplayStore("cycle-test", signals)
    replay_store.set_round(1)

    mock_replay_manager = MagicMock()
    mock_replay_manager.is_active = True
    mock_replay_manager.store = replay_store

    result = snapshot_to_json(state_store, replay_manager=mock_replay_manager)
    data = json.loads(result)
    assert data["phase"] == "replay"
    assert "agent_1" in data["agent_states"]
    assert data["agent_states"]["agent_1"]["signal"] == "buy"
