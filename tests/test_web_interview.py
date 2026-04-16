"""Tests for POST /api/interview/{agent_id} endpoint (Phase 35 Plan 01)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.types import SimulationPhase


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_interview_test_app() -> FastAPI:
    """Build a test-friendly FastAPI app that includes the interview router.

    Copies the pattern from _make_test_app() in test_web.py.
    Adds:
    - app.state.interview_sessions = {} in lifespan
    - interview_router registered at prefix="/api"
    """
    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.interview import router as interview_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _interview_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        sim_manager = SimulationManager(app_state, brackets)
        replay_manager = ReplayManager(app_state)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager
        # Per D-06 and review consensus: interview sessions dict cleared on each new run
        app.state.interview_sessions = {}

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-Interview-Test", lifespan=_interview_lifespan)
    app.include_router(interview_router, prefix="/api")
    return app


def _mock_complete_app_state(app: FastAPI) -> None:
    """Helper: set app.state.app_state.state_store snapshot to COMPLETE phase."""
    from unittest.mock import MagicMock

    mock_snap = MagicMock()
    mock_snap.phase = SimulationPhase.COMPLETE
    app.state.app_state.state_store = MagicMock()
    app.state.app_state.state_store.snapshot = MagicMock(return_value=mock_snap)


# ---------------------------------------------------------------------------
# Test 1: 503 when graph_manager is None
# ---------------------------------------------------------------------------


def test_interview_503_no_graph() -> None:
    """POST /api/interview/{agent_id} returns 503 when graph_manager is None."""
    app = _make_interview_test_app()
    with TestClient(app) as client:
        # graph_manager is None by default (no neo4j in test app)
        r = client.post("/api/interview/agent_1", json={"message": "hello"})
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "services_unavailable"


# ---------------------------------------------------------------------------
# Test 2: 503 when ollama_client is None
# ---------------------------------------------------------------------------


def test_interview_503_no_ollama() -> None:
    """POST /api/interview/{agent_id} returns 503 when ollama_client is None."""
    from unittest.mock import AsyncMock

    app = _make_interview_test_app()
    with TestClient(app) as client:
        app.state.app_state.graph_manager = AsyncMock()
        # ollama_client is None by default (no ollama in test app)
        r = client.post("/api/interview/agent_1", json={"message": "hello"})
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "services_unavailable"


# ---------------------------------------------------------------------------
# Test 3: 409 when phase is not COMPLETE
# ---------------------------------------------------------------------------


def test_interview_409_phase_not_complete() -> None:
    """POST /api/interview/{agent_id} returns 409 when simulation is in progress."""
    from unittest.mock import AsyncMock, MagicMock

    app = _make_interview_test_app()
    with TestClient(app) as client:
        app.state.app_state.graph_manager = AsyncMock()
        app.state.app_state.ollama_client = MagicMock()
        mock_snap = MagicMock()
        mock_snap.phase = SimulationPhase.ROUND_2
        app.state.app_state.state_store = MagicMock()
        app.state.app_state.state_store.snapshot = MagicMock(return_value=mock_snap)
        r = client.post("/api/interview/agent_1", json={"message": "hello"})
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "interview_unavailable"


# ---------------------------------------------------------------------------
# Test 4: 404 when no completed cycles exist
# ---------------------------------------------------------------------------


def test_interview_404_no_cycles() -> None:
    """POST /api/interview/{agent_id} returns 404 when read_completed_cycles returns []."""
    from unittest.mock import AsyncMock, MagicMock

    app = _make_interview_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_completed_cycles = AsyncMock(return_value=[])
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)
        r = client.post("/api/interview/agent_1", json={"message": "hello"})
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "no_completed_cycle"


# ---------------------------------------------------------------------------
# Test 5: 404 when read_agent_interview_context returns None
# ---------------------------------------------------------------------------


def test_interview_404_empty_context() -> None:
    """POST /api/interview/{agent_id} returns 404 when read_agent_interview_context returns None."""
    from unittest.mock import AsyncMock, MagicMock

    app = _make_interview_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_completed_cycles = AsyncMock(return_value=[{"cycle_id": "c1"}])
        mock_gm.read_agent_interview_context = AsyncMock(return_value=None)
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)
        r = client.post("/api/interview/agent_1", json={"message": "hello"})
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "agent_not_found"


# ---------------------------------------------------------------------------
# Test 6: 422 when message is empty (min_length=1 violated)
# ---------------------------------------------------------------------------


def test_interview_422_empty_message() -> None:
    """POST /api/interview/{agent_id} returns 422 when message is empty."""
    app = _make_interview_test_app()
    with TestClient(app) as client:
        r = client.post("/api/interview/agent_1", json={"message": ""})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Test 7: 422 when message exceeds max_length=4000
# ---------------------------------------------------------------------------


def test_interview_422_message_too_long() -> None:
    """POST /api/interview/{agent_id} returns 422 when message is 4001 chars."""
    app = _make_interview_test_app()
    with TestClient(app) as client:
        r = client.post("/api/interview/agent_1", json={"message": "x" * 4001})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Test 8: Happy path — 200 with response body
# ---------------------------------------------------------------------------


def test_interview_endpoint_returns_response() -> None:
    """POST /api/interview/{agent_id} returns 200 with {"response": "..."} on happy path."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.interview import InterviewContext, RoundDecision

    app = _make_interview_test_app()
    with TestClient(app) as client:
        mock_context = InterviewContext(
            agent_id="agent_1",
            agent_name="TestAgent",
            bracket="quants",
            interview_system_prompt="You are TestAgent.",
            decision_narrative="TestAgent decided to BUY.",
            decisions=[RoundDecision(round_num=1, signal="buy", confidence=0.9, sentiment=0.7, rationale="good news")],
        )
        mock_gm = AsyncMock()
        mock_gm.read_completed_cycles = AsyncMock(return_value=[{"cycle_id": "c1"}])
        mock_gm.read_agent_interview_context = AsyncMock(return_value=mock_context)
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)

        mock_engine = MagicMock()
        mock_engine.ask = AsyncMock(return_value="mock response")

        with patch("alphaswarm.web.routes.interview.InterviewEngine", return_value=mock_engine) as MockCls:
            r = client.post("/api/interview/agent_1", json={"message": "Why did you buy?"})
            assert r.status_code == 200
            data = r.json()
            assert data["response"] == "mock response"
            assert MockCls.call_count == 1


# ---------------------------------------------------------------------------
# Test 9: Multi-turn — second call reuses same InterviewEngine
# ---------------------------------------------------------------------------


def test_interview_multi_turn() -> None:
    """Two sequential POSTs for same agent_id reuse the same InterviewEngine."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.interview import InterviewContext, RoundDecision

    app = _make_interview_test_app()
    with TestClient(app) as client:
        mock_context = InterviewContext(
            agent_id="agent_1",
            agent_name="TestAgent",
            bracket="quants",
            interview_system_prompt="You are TestAgent.",
            decision_narrative="TestAgent decided to BUY.",
            decisions=[RoundDecision(round_num=1, signal="buy", confidence=0.9, sentiment=0.7, rationale="good")],
        )
        mock_gm = AsyncMock()
        mock_gm.read_completed_cycles = AsyncMock(return_value=[{"cycle_id": "c1"}])
        mock_gm.read_agent_interview_context = AsyncMock(return_value=mock_context)
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)

        mock_engine = MagicMock()
        mock_engine.ask = AsyncMock(return_value="response")

        with patch("alphaswarm.web.routes.interview.InterviewEngine", return_value=mock_engine) as MockCls:
            r1 = client.post("/api/interview/agent_1", json={"message": "Question 1"})
            r2 = client.post("/api/interview/agent_1", json={"message": "Question 2"})
            assert r1.status_code == 200
            assert r2.status_code == 200
            # Engine instantiated exactly once, ask called twice
            assert MockCls.call_count == 1
            assert mock_engine.ask.call_count == 2


# ---------------------------------------------------------------------------
# Test 10: Session reuse — read_agent_interview_context called once across 2 requests
# ---------------------------------------------------------------------------


def test_interview_session_reuse() -> None:
    """read_agent_interview_context is called exactly once across 2 requests to same agent."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.interview import InterviewContext, RoundDecision

    app = _make_interview_test_app()
    with TestClient(app) as client:
        mock_context = InterviewContext(
            agent_id="agent_1",
            agent_name="TestAgent",
            bracket="quants",
            interview_system_prompt="You are TestAgent.",
            decision_narrative="Narrative.",
            decisions=[RoundDecision(round_num=1, signal="buy", confidence=0.8, sentiment=0.6, rationale="ok")],
        )
        mock_gm = AsyncMock()
        mock_gm.read_completed_cycles = AsyncMock(return_value=[{"cycle_id": "c1"}])
        mock_gm.read_agent_interview_context = AsyncMock(return_value=mock_context)
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)

        mock_engine = MagicMock()
        mock_engine.ask = AsyncMock(return_value="answer")

        with patch("alphaswarm.web.routes.interview.InterviewEngine", return_value=mock_engine):
            client.post("/api/interview/agent_1", json={"message": "Q1"})
            client.post("/api/interview/agent_1", json={"message": "Q2"})
            assert mock_gm.read_agent_interview_context.call_count == 1


# ---------------------------------------------------------------------------
# Test 11: Concurrent requests for same agent serialize (per-agent lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_concurrent_same_agent_serializes() -> None:
    """Two concurrent POSTs for same agent_id both complete; engine.ask never runs in parallel."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.interview import InterviewContext, RoundDecision

    app = _make_interview_test_app()

    mock_context = InterviewContext(
        agent_id="agent_1",
        agent_name="TestAgent",
        bracket="quants",
        interview_system_prompt="You are TestAgent.",
        decision_narrative="Narrative.",
        decisions=[RoundDecision(round_num=1, signal="buy", confidence=0.9, sentiment=0.7, rationale="ok")],
    )
    mock_gm = AsyncMock()
    mock_gm.read_completed_cycles = AsyncMock(return_value=[{"cycle_id": "c1"}])
    mock_gm.read_agent_interview_context = AsyncMock(return_value=mock_context)

    # Track concurrency overlap
    max_concurrent = 0
    current = 0

    async def tracked_ask(msg: str) -> str:
        nonlocal max_concurrent, current
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.05)  # simulate LLM latency
        current -= 1
        return "ok"

    mock_engine = MagicMock()
    mock_engine.ask = tracked_ask

    with TestClient(app) as client:
        app.state.app_state.graph_manager = mock_gm
        app.state.app_state.ollama_client = MagicMock()
        _mock_complete_app_state(app)

        with patch("alphaswarm.web.routes.interview.InterviewEngine", return_value=mock_engine):
            # Use threading to simulate concurrent requests via TestClient
            import threading

            results: list[int] = []

            def make_request() -> None:
                r = client.post("/api/interview/agent_1", json={"message": "question"})
                results.append(r.status_code)

            t1 = threading.Thread(target=make_request)
            t2 = threading.Thread(target=make_request)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

    assert all(s == 200 for s in results), f"Expected 200s, got: {results}"
    assert max_concurrent == 1, f"Expected max 1 concurrent ask, got {max_concurrent}"


# ---------------------------------------------------------------------------
# Test 12: Sessions cleared on new simulation start
# ---------------------------------------------------------------------------


def test_interview_sessions_cleared_on_new_simulation() -> None:
    """After populating interview_sessions, calling sim_manager.start() clears them."""
    from unittest.mock import AsyncMock, patch

    app = _make_interview_test_app()
    with TestClient(app) as client:
        # Pre-populate interview_sessions
        app.state.interview_sessions["agent_1"] = object()
        app.state.interview_sessions["agent_2"] = object()
        assert len(app.state.interview_sessions) == 2

        # Patch _run so start() completes without real simulation
        with patch.object(app.state.sim_manager, "_run", AsyncMock(return_value=None)):
            asyncio.get_event_loop().run_until_complete(
                app.state.sim_manager.start("new seed")
            )

        assert app.state.interview_sessions == {}


# ---------------------------------------------------------------------------
# Test 13: Interview route registered in production app
# ---------------------------------------------------------------------------


def test_interview_route_registered_in_production_app() -> None:
    """Production create_app() includes /api/interview/{agent_id} route."""
    from alphaswarm.web.app import create_app as production_create_app

    prod_app = production_create_app()
    route_paths = [getattr(r, "path", None) for r in prod_app.routes]
    assert "/api/interview/{agent_id}" in route_paths, (
        f"/api/interview/{{agent_id}} not registered. Found: {route_paths}"
    )
