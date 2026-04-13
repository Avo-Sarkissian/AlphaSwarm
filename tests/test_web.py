"""Tests for AlphaSwarm web package: health endpoint, lifespan, SimulationManager, ConnectionManager."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.simulation_manager import SimulationAlreadyRunningError, SimulationManager
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
    from alphaswarm.web.routes.health import router as health_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _unit_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Use _env_file=None to skip the .env file with extra keys
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        # with_ollama=False, with_neo4j=False for unit tests (no external services)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        sim_manager = SimulationManager(app_state)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.connection_manager = connection_manager

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-Test", lifespan=_unit_lifespan)
    app.include_router(health_router, prefix="/api")
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
    sm = SimulationManager(mock_app_state)

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
