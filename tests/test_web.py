"""Tests for AlphaSwarm web package: health endpoint, lifespan, SimulationManager,
ConnectionManager, WebSocket state stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.simulation_manager import (
    NoSimulationRunningError,
    ShockAlreadyQueuedError,
    SimulationAlreadyRunningError,
    SimulationManager,
)
from tests.support.web_app import CYCLE_A, CYCLE_B, CYCLE_UNKNOWN

# ---------------------------------------------------------------------------
# Test helpers — lightweight lifespan that bypasses .env / Neo4j / Ollama
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Build a test-friendly FastAPI app with a clean-env lifespan.

    Uses AppSettings(_env_file=None) to avoid the .env file's extra keys
    that would fail Pydantic strict validation in unit tests.
    """

    from alphaswarm.app import create_app_state
    from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider
    from alphaswarm.personas import generate_personas, load_bracket_configs
    from alphaswarm.settings import AppSettings
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.errors import install_error_handlers
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.edges import router as edges_router
    from alphaswarm.web.routes.health import router as health_router
    from alphaswarm.web.routes.interview import router as interview_router
    from alphaswarm.web.routes.replay import router as replay_router
    from alphaswarm.web.routes.report import router as report_router
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
        # m8x Task 3: construct ReplayManager BEFORE SimulationManager so the
        # latter can hold a reference for the B4 replay-active guard.
        replay_manager = ReplayManager(app_state)
        sim_manager = SimulationManager(app_state, brackets, replay_manager=replay_manager)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager
        app.state.interview_sessions = {}

        # Phase 40 D-10: mirror production provider wiring in the isolated test lifespan.
        # Construction is synchronous and does no network I/O — preserves with_ollama=False,
        # with_neo4j=False isolation posture.
        market_provider = YFinanceMarketDataProvider()
        news_provider = RSSNewsProvider()
        app.state.market_provider = market_provider
        app.state.news_provider = news_provider
        app_state.market_provider = market_provider
        app_state.news_provider = news_provider

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-Test", lifespan=_unit_lifespan)
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(simulation_router, prefix="/api")
    app.include_router(edges_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(interview_router, prefix="/api")
    app.include_router(report_router, prefix="/api")
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
        assert data["status"] == "degraded"  # test app: no Neo4j, no Ollama
        assert data["components"]["neo4j"]["ok"] is False
        assert isinstance(data["simulation_phase"], str)
        assert isinstance(data["memory_percent"], float)
        assert data["is_simulation_running"] is False
        # New additive fields must also be present
        assert "inference_mode" in data
        assert "spent_usd" in data


def test_health_inference_mode_default_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """inference_mode is 'local' when no inference config file exists.

    hermetic_env points the config path at a missing temp file, so the
    operator's real .secrets/inference.json can no longer change this answer.
    """
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["inference_mode"] == "local"


def test_health_inference_mode_reflects_cloud_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """inference_mode returns 'cloud' when load_inference_config returns a cloud-only config."""
    from unittest.mock import MagicMock

    from alphaswarm.inference.config import ProviderType, RoleConfig

    def _fake_load(settings: object, path: object = None) -> MagicMock:  # type: ignore[return]
        cfg = MagicMock()
        cloud_role = RoleConfig(
            provider=ProviderType.ANTHROPIC,
            model="claude-sonnet-4-5",
            api_key="sk-test",
        )
        cfg.orchestrator = cloud_role
        cfg.worker = cloud_role
        return cfg

    monkeypatch.setattr("alphaswarm.web.routes.health.load_inference_config", _fake_load)
    monkeypatch.setattr(
        "alphaswarm.web.routes.health.inference_mode",
        lambda cfg: "cloud",
    )

    with TestClient(_make_test_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["inference_mode"] == "cloud"


def test_health_inference_mode_degrades_to_local_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """inference_mode degrades to 'local' (not 500) when load_inference_config raises."""
    monkeypatch.setattr(
        "alphaswarm.web.routes.health.load_inference_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad config")),
    )

    with TestClient(_make_test_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["inference_mode"] == "local"


def test_health_spent_usd_null_when_no_budget_meter() -> None:
    """spent_usd is null when app_state has no budget_meter attribute."""
    with TestClient(_make_test_app()) as client:
        # The test app_state created by _make_test_app does not set budget_meter
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["spent_usd"] is None


def test_health_spent_usd_float_when_budget_meter_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """spent_usd is a float when app_state.budget_meter is set."""
    from decimal import Decimal
    from unittest.mock import MagicMock

    app = _make_test_app()
    with TestClient(app) as client:
        fake_meter = MagicMock()
        fake_meter.spent.return_value = Decimal("1.23")
        # Set budget_meter on app_state (simulating what SimulationManager._run does)
        app.state.app_state.budget_meter = fake_meter  # type: ignore[attr-defined]

        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["spent_usd"] == pytest.approx(1.23)
        assert isinstance(data["spent_usd"], float)


def test_health_spent_usd_zero_for_local_run() -> None:
    """spent_usd is 0.0 (not null) when budget_meter exists but no cloud calls have been made."""
    from decimal import Decimal
    from unittest.mock import MagicMock

    app = _make_test_app()
    with TestClient(app) as client:
        fake_meter = MagicMock()
        fake_meter.spent.return_value = Decimal("0")
        app.state.app_state.budget_meter = fake_meter  # type: ignore[attr-defined]

        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["spent_usd"] == 0.0


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


def test_lifespan_wires_providers() -> None:
    """Phase 40 D-10: lifespan constructs YFinance + RSS providers on app.state,
    mirrored onto app_state for SimulationManager consumption.

    Uses the isolated _make_test_app() helper (AppSettings(_env_file=None),
    with_ollama=False, with_neo4j=False) per REVIEWS feedback — production
    create_app() would pull in .env/Neo4j/Ollama side effects that break
    the existing test isolation pattern.
    """
    from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider

    with TestClient(_make_test_app()) as client:
        # Inside `with`: lifespan startup has completed.
        assert isinstance(client.app.state.market_provider, YFinanceMarketDataProvider)
        assert isinstance(client.app.state.news_provider, RSSNewsProvider)
        # Identity: app_state mirrors app.state (same object, not copies).
        # This is the contract SimulationManager._run depends on.
        assert client.app.state.app_state.market_provider is client.app.state.market_provider
        assert client.app.state.app_state.news_provider is client.app.state.news_provider


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
# Test 7: POST /api/simulate/start returns 409 when simulation is running (SC-4)
# ---------------------------------------------------------------------------


def test_simulate_start_409_when_running() -> None:
    """POST /api/simulate/start returns HTTP 409 when simulation is already running."""
    from unittest.mock import AsyncMock, patch

    from alphaswarm.web.simulation_manager import SimulationAlreadyRunningError

    with (
        TestClient(_make_test_app()) as client,
        patch.object(
            client.app.state.sim_manager,
            "start",
            new=AsyncMock(side_effect=SimulationAlreadyRunningError("Simulation already running")),
        ),
    ):
        r = client.post("/api/simulate/start", json={"seed": "test seed rumor"})
        assert r.status_code == 409
        data = r.json()
        assert "detail" in data
        assert data["detail"]["error"] == "simulation_already_running"


# ---------------------------------------------------------------------------
# Phase 30: WebSocket State Stream test helpers
# ---------------------------------------------------------------------------


def _make_ws_test_app() -> FastAPI:
    """FastAPI test app for WebSocket tests. Starts broadcaster (unlike _unit_lifespan)."""

    from alphaswarm.app import create_app_state
    from alphaswarm.personas import generate_personas, load_bracket_configs
    from alphaswarm.settings import AppSettings
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
        with suppress(asyncio.CancelledError):
            await broadcaster_task

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


# ---------------------------------------------------------------------------
# Phase 999.3 Plan 01: Live memory% overlay tests (MEM-01/02/03, D-01)
# ---------------------------------------------------------------------------


def test_snapshot_to_json_includes_live_memory_percent_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEM-01: IDLE phase (governor_metrics=None): non-None governor_metrics with live memory %."""
    import json

    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    store = StateStore()
    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 42.0)
    parsed = json.loads(snapshot_to_json(store))
    assert parsed["governor_metrics"] is not None
    assert parsed["governor_metrics"]["memory_percent"] == 42.0
    assert parsed["governor_metrics"]["current_slots"] == 0
    assert parsed["governor_metrics"]["active_count"] == 0
    assert parsed["governor_metrics"]["pressure_level"] == "green"
    assert parsed["governor_metrics"]["governor_state"] == "idle"
    assert "timestamp" in parsed["governor_metrics"]


def test_snapshot_to_json_overlays_memory_percent_when_governor_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEM-01: Stale GovernorMetrics is overlaid with fresh memory % by broadcaster."""
    import json

    from alphaswarm.state import GovernorMetrics, StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    store = StateStore()
    stale_gm = GovernorMetrics(
        current_slots=8,
        active_count=3,
        pressure_level="green",
        memory_percent=11.1,
        governor_state="running",
        timestamp=100.0,
    )
    store.update_governor_metrics(stale_gm)
    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 73.5)
    parsed = json.loads(snapshot_to_json(store))
    # Fresh reading wins over stale governor value
    assert parsed["governor_metrics"]["memory_percent"] == 73.5
    # Governor-authoritative fields are preserved
    assert parsed["governor_metrics"]["current_slots"] == 8
    assert parsed["governor_metrics"]["active_count"] == 3
    assert parsed["governor_metrics"]["governor_state"] == "running"


def test_broadcaster_emits_fresh_memory_percent_per_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEM-02: Each call to snapshot_to_json reads memory % fresh (not cached across calls)."""
    import json

    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    store = StateStore()
    vals = [50.0, 55.0, 60.0]
    call_count = [0]

    def _fake_used_percent() -> float:
        result = vals[call_count[0]]
        call_count[0] += 1
        return result

    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", _fake_used_percent)
    results = [json.loads(snapshot_to_json(store)) for _ in range(3)]
    assert results[0]["governor_metrics"]["memory_percent"] == 50.0
    assert results[1]["governor_metrics"]["memory_percent"] == 55.0
    assert results[2]["governor_metrics"]["memory_percent"] == 60.0


def test_overlay_preserves_governor_authoritative_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEM-03: Overlay only replaces memory_percent; all other governor fields unchanged."""
    import json

    from alphaswarm.state import GovernorMetrics, StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    store = StateStore()
    original_gm = GovernorMetrics(
        current_slots=12,
        active_count=5,
        pressure_level="yellow",
        memory_percent=11.1,
        governor_state="throttled",
        timestamp=999.0,
    )
    store.update_governor_metrics(original_gm)
    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 88.8)
    parsed = json.loads(snapshot_to_json(store))
    gm = parsed["governor_metrics"]
    # Only memory_percent changes
    assert gm["memory_percent"] == 88.8
    # All other fields match original governor metrics
    assert gm["current_slots"] == 12
    assert gm["active_count"] == 5
    assert gm["pressure_level"] == "yellow"
    assert gm["governor_state"] == "throttled"
    assert gm["timestamp"] == 999.0


def test_replay_mode_memory_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-01: Replay mode includes live host RAM% overlay (not sentinel/zero)."""
    import json
    from types import SimpleNamespace

    from alphaswarm.state import ReplayStore, StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    replay_store = ReplayStore(cycle_id="test-cycle", signals={})
    replay_store.set_round(1)
    replay_manager = SimpleNamespace(is_active=True, has_store=True, store=replay_store)
    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 88.0)
    parsed = json.loads(snapshot_to_json(state_store=StateStore(), replay_manager=replay_manager))
    assert parsed["phase"] == "replay"
    assert parsed["governor_metrics"] is not None
    assert parsed["governor_metrics"]["memory_percent"] == 88.0


async def test_broadcaster_cancellation() -> None:
    """start_broadcaster returns a cancellable asyncio.Task."""
    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import start_broadcaster

    store = StateStore()
    cm = ConnectionManager()
    task = start_broadcaster(store, cm)
    assert not task.done()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


def test_ws_state_receives_snapshot() -> None:
    """Connecting to /ws/state receives JSON when broadcaster sends."""
    import json

    app = _make_ws_test_app()
    with TestClient(app) as client, client.websocket_connect("/ws/state") as ws:
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
        with client.websocket_connect("/ws/state"):
            assert client.app.state.connection_manager.client_count == 1
        # After exiting context manager, disconnect should have fired
        assert client.app.state.connection_manager.client_count == 0


def test_ws_state_same_connection_manager() -> None:
    """Broadcaster and /ws/state endpoint share the same connection_manager object."""
    import json

    app = _make_ws_test_app()
    with TestClient(app) as client, client.websocket_connect("/ws/state") as ws:
        # Broadcasting via app.state.connection_manager should reach the WS client
        # This proves the route handler and lifespan use the same object
        cm = client.app.state.connection_manager
        cm.broadcast(json.dumps({"phase": "identity_check"}))
        data = ws.receive_text()
        parsed = json.loads(data)
        assert parsed["phase"] == "identity_check"


# ---------------------------------------------------------------------------
# F2: /ws/state Origin allow-list (cross-site WebSocket hijacking guard)
# ---------------------------------------------------------------------------


def test_ws_state_allows_configured_origin() -> None:
    """F2: an Origin in AppSettings.allowed_origins connects normally."""
    app = _make_ws_test_app()
    with TestClient(app) as client, client.websocket_connect("/ws/state", headers={"origin": "http://localhost:5173"}):
        assert client.app.state.connection_manager.client_count == 1


def test_ws_state_refuses_an_origin_derived_from_the_host_header() -> None:
    """The request's own Host is not an allow-list entry: a DNS-rebinding page
    controls Host, so Origin http://testserver (TestClient's Host) is refused."""
    from starlette.websockets import WebSocketDisconnect

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            client.websocket_connect("/ws/state", headers={"origin": "http://testserver"}),
        ):
            pass
        assert excinfo.value.code == 1008
        assert client.app.state.connection_manager.client_count == 0


@pytest.mark.parametrize("origin", ["http://localhost:8000", "HTTP://LOCALHOST:8000/"])
def test_ws_state_allows_the_served_spa_origin(origin: str) -> None:
    """The built UI on uvicorn (port 8000) connects; spelling differences fold."""
    app = _make_ws_test_app()
    with TestClient(app) as client, client.websocket_connect("/ws/state", headers={"origin": origin}):
        assert client.app.state.connection_manager.client_count == 1


def test_ws_state_allows_missing_origin() -> None:
    """F2: a handshake with no Origin header (non-browser client) is still accepted.

    Browsers always send Origin on a WS handshake, so this path is not the
    cross-site vector — refusing it would break wscat/scripts/tests.
    """
    app = _make_ws_test_app()
    with TestClient(app) as client, client.websocket_connect("/ws/state"):
        assert client.app.state.connection_manager.client_count == 1


def test_ws_state_refuses_foreign_origin_before_accept() -> None:
    """F2: a foreign Origin is closed with 1008 and never allocates a client slot."""
    from starlette.websockets import WebSocketDisconnect

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            client.websocket_connect("/ws/state", headers={"origin": "https://evil.example"}),
        ):
            pass
        assert excinfo.value.code == 1008
        # Refused before connection_manager.connect(): no queue, no writer task.
        assert client.app.state.connection_manager.client_count == 0


def test_ws_state_refuses_null_origin() -> None:
    """F2: the opaque "null" origin (sandboxed iframe, data: URL) is refused."""
    from starlette.websockets import WebSocketDisconnect

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            client.websocket_connect("/ws/state", headers={"origin": "null"}),
        ):
            pass
        assert excinfo.value.code == 1008
        assert client.app.state.connection_manager.client_count == 0


@pytest.mark.parametrize("malformed_host", ["]", "[x]"])
def test_ws_state_malformed_host_refuses_cleanly(malformed_host: str) -> None:
    """F2: a bracket-malformed Host takes the normal refusal path, never a 500.

    Starlette's WebSocket.url lazily urlsplit()s the raw Host header and raises
    ValueError ("Invalid IPv6 URL") on unbalanced brackets, which h11/uvicorn
    happily pass through. Deriving the server origin from scope["scheme"]
    instead keeps an unauthenticated peer from turning each handshake into an
    unhandled endpoint error. TestClient re-raises endpoint exceptions, so a
    regression here surfaces as ValueError instead of WebSocketDisconnect.
    """
    from starlette.websockets import WebSocketDisconnect

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            client.websocket_connect(
                "/ws/state",
                headers={"origin": "https://evil.example", "host": malformed_host},
            ),
        ):
            pass
        assert excinfo.value.code == 1008
        assert client.app.state.connection_manager.client_count == 0


def test_safe_origin_for_log_bounds_and_neutralizes() -> None:
    """F2: the log helper truncates and strips whitespace/control chars."""
    from alphaswarm.web.routes.websocket import (
        _MAX_LOGGED_ORIGIN_CHARS,
        _ORIGIN_TRUNCATION_MARKER,
        _safe_origin_for_log,
    )

    assert _safe_origin_for_log(None) == "<none>"
    assert _safe_origin_for_log("http://localhost:5173") == "http://localhost:5173"

    forged = _safe_origin_for_log("x event=ws_state_connected\tclient=1\x07")
    assert not any(c.isspace() for c in forged)
    assert "\x07" not in forged

    long_origin = _safe_origin_for_log("http://" + "a" * 5000)
    assert len(long_origin) == _MAX_LOGGED_ORIGIN_CHARS + len(_ORIGIN_TRUNCATION_MARKER)
    assert long_origin.endswith(_ORIGIN_TRUNCATION_MARKER)


def test_ws_state_refused_origin_logged_bounded_and_neutralized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2: the Origin bound to the refusal log event is bounded and whitespace-free.

    Under ALPHASWARM_DEBUG=true structlog renders str values verbatim, so an
    unbounded Origin containing spaces would forge extra key=value pairs in the
    console line (and let a peer push ~16 KB of text per handshake into the log).
    """
    from starlette.websockets import WebSocketDisconnect

    from alphaswarm.web.routes import websocket as ws_module

    records: list[tuple[str, dict[str, object]]] = []

    class _RecordingLog:
        def info(self, event: str, **kwargs: object) -> None:
            records.append((event, kwargs))

        def warning(self, event: str, **kwargs: object) -> None:
            records.append((event, kwargs))

    monkeypatch.setattr(ws_module, "log", _RecordingLog())

    hostile = "http://evil.example client=127.0.0.1 event=ws_state_connected " + "A" * 500

    app = _make_ws_test_app()
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/state", headers={"origin": hostile}):
            pass
        assert client.app.state.connection_manager.client_count == 0

    refusals = [kwargs for event, kwargs in records if event == "ws_state_origin_refused"]
    assert len(refusals) == 1
    logged = refusals[0]["origin"]
    assert isinstance(logged, str)
    assert len(logged) < 100  # bounded — nothing like the 500+ chars the peer sent
    assert not any(c.isspace() for c in logged)  # cannot forge extra key=value pairs


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
        f"/ws/state not registered in production create_app(). Found routes: {route_paths}"
    )


# ---------------------------------------------------------------------------
# Phase 31: Edges endpoint tests (VIS-03)
# ---------------------------------------------------------------------------


def test_edges_endpoint_503_without_neo4j() -> None:
    """GET /api/edges/{cycle_id}?round=1 returns 503 when graph_manager is None."""
    with TestClient(_make_test_app()) as client:
        r = client.get(f"/api/edges/{CYCLE_A}?round=1")
        assert r.status_code == 503
        data = r.json()
        assert data["detail"]["error"] == "graph_unavailable"


def test_edges_endpoint_requires_round_param() -> None:
    """GET /api/edges/{cycle_id} without round query param returns 422."""
    with TestClient(_make_test_app()) as client:
        r = client.get(f"/api/edges/{CYCLE_A}")
        assert r.status_code == 422


def test_edges_endpoint_round_validation() -> None:
    """GET /api/edges/{cycle_id}?round=0 returns 422 (round must be 1-3)."""
    with TestClient(_make_test_app()) as client:
        r = client.get(f"/api/edges/{CYCLE_A}?round=0")
        assert r.status_code == 422
        r2 = client.get(f"/api/edges/{CYCLE_A}?round=4")
        assert r2.status_code == 422


def test_edges_route_registered_in_production_app() -> None:
    """Production create_app() registers /api/edges/{cycle_id} route."""
    from alphaswarm.web.app import create_app as production_create_app

    prod_app = production_create_app()
    route_paths = [getattr(r, "path", None) for r in prod_app.routes]
    assert "/api/edges/{cycle_id}" in route_paths, f"/api/edges/{{cycle_id}} not registered. Found: {route_paths}"


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
    mock_app_state.state_store.set_last_error = AsyncMock()
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
    mock_app_state.state_store.set_last_error = AsyncMock()
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
    mock_app_state.state_store.set_last_error = AsyncMock()
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
    mock_app_state.state_store.set_last_error = AsyncMock()
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


async def test_sim_manager_run_passes_consume_shock() -> None:
    """Phase 35.1 — SimulationManager._run forwards consume_shock=self.consume_shock
    to run_simulation."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_app_state = MagicMock()
    mock_app_state.state_store = MagicMock()
    mock_app_state.state_store.set_last_error = AsyncMock()
    mock_app_state.state_store.set_phase = AsyncMock()
    sm = SimulationManager(mock_app_state, brackets=[])

    called_kwargs: dict = {}

    async def _capture_run(*args: object, **kwargs: object) -> None:
        called_kwargs.update(kwargs)

    # Patch inference factory functions so the test does not need a real AppSettings object.
    mock_built = MagicMock()
    mock_built.orchestrator.aclose = AsyncMock()
    mock_built.worker.aclose = AsyncMock()
    with (
        patch("alphaswarm.inference.config.load_inference_config", return_value=MagicMock()),
        patch("alphaswarm.inference.factory.build_providers", return_value=mock_built),
        patch("alphaswarm.inference.factory.build_controller", return_value=MagicMock()),
        patch("alphaswarm.services.runtime.InferenceRuntime.run_provenance", new=AsyncMock(return_value=None)),
        patch("alphaswarm.inference.factory.inference_mode", return_value="local"),
        patch("alphaswarm.simulation.run_simulation", new=AsyncMock(side_effect=_capture_run)),
    ):
        await sm.start("test seed")
        # Allow the background task a tick to await run_simulation.
        await asyncio.sleep(0.05)
        # Task should have completed (run_simulation returns immediately via _capture_run).
        if sm._task is not None:
            await sm._task

    assert "consume_shock" in called_kwargs, (
        f"run_simulation was NOT called with consume_shock kwarg. kwargs received: {sorted(called_kwargs.keys())}"
    )
    # The forwarded value must be the manager's own consume_shock bound method
    # (not a newly created lambda), so replays see pending shock state.
    assert called_kwargs["consume_shock"] == sm.consume_shock, (
        "consume_shock kwarg must be the SimulationManager.consume_shock bound method"
    )


# ---------------------------------------------------------------------------
# Phase 32 Task 2: Stop and shock REST endpoints + cancellation phase reset
# ---------------------------------------------------------------------------


def test_simulate_start_202() -> None:
    """POST /api/simulate/start returns 202 with accepted status."""
    from unittest.mock import AsyncMock, patch

    with (
        TestClient(_make_test_app()) as client,
        patch.object(
            client.app.state.sim_manager,
            "start",
            new=AsyncMock(),
        ),
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
            r = client.post("/api/simulate/shock", json={"shock_text": "market crash again"})
            assert r.status_code == 409
            data = r.json()
            assert data["detail"]["error"] == "no_simulation_running"


def test_simulate_shock_concurrent_409() -> None:
    """POST /api/simulate/shock returns 409 when shock already queued."""
    from unittest.mock import MagicMock, patch

    from alphaswarm.web.simulation_manager import ShockAlreadyQueuedError

    with (
        TestClient(_make_test_app()) as client,
        patch.object(
            client.app.state.sim_manager,
            "inject_shock",
            new=MagicMock(side_effect=ShockAlreadyQueuedError("A shock is already queued")),
        ),
    ):
        r = client.post("/api/simulate/shock", json={"shock_text": "another shock"})
        assert r.status_code == 409
        data = r.json()
        assert data["detail"]["error"] == "shock_already_queued"


async def test_sim_manager_cancellation_resets_phase_to_idle() -> None:
    """Cancelling a simulation resets StateStore.phase to IDLE.

    Post-m8x (B8 fix): the phase reset now lives inside _run's try/except
    block (awaited synchronously before the done-callback fires), not as a
    fire-and-forget task scheduled in _on_task_done. To exercise that path
    we must patch alphaswarm.simulation.run_simulation at the module level
    so the real _run with its try/except runs, rather than patching _run
    itself (which would short-circuit the fix).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.types import SimulationPhase

    mock_app_state = MagicMock()
    mock_state_store = MagicMock()
    mock_state_store.set_last_error = AsyncMock()
    mock_state_store.set_phase = AsyncMock()
    mock_app_state.state_store = mock_state_store
    mock_app_state.personas = []
    sm = SimulationManager(mock_app_state, brackets=[])

    async def _long_run(**kwargs: object) -> None:
        await asyncio.sleep(100)

    mock_built = MagicMock()
    mock_built.orchestrator.aclose = AsyncMock()
    mock_built.worker.aclose = AsyncMock()
    # Patch inference factory functions so the test does not need a real AppSettings object.
    # Patch run_simulation so the REAL _run runs (including the B8 try/except).
    with (
        patch("alphaswarm.inference.config.load_inference_config", return_value=MagicMock()),
        patch("alphaswarm.inference.factory.build_providers", return_value=mock_built),
        patch("alphaswarm.inference.factory.build_controller", return_value=MagicMock()),
        patch("alphaswarm.services.runtime.InferenceRuntime.run_provenance", new=AsyncMock(return_value=None)),
        patch("alphaswarm.inference.factory.inference_mode", return_value="local"),
        patch("alphaswarm.simulation.run_simulation", new=AsyncMock(side_effect=_long_run)),
    ):
        await sm.start("test seed")
        # Yield once so the background task reaches `await run_simulation(...)`
        # before stop() cancels it — otherwise the task body never runs and
        # the except block never executes.
        await asyncio.sleep(0)
        sm.stop()

        # Wait for cancellation + in-_run phase reset + done-callback
        await asyncio.sleep(0.1)

        # Verify set_phase(IDLE) was called by _run's except block
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


def test_replay_cycles_lists_completed_cycles() -> None:
    """GET /api/replay/cycles returns each completed cycle from the graph as a CycleItem."""
    from unittest.mock import AsyncMock

    row = {
        "cycle_id": CYCLE_A,
        "created_at": "2026-10-01T12:00:00+00:00",
        "seed_rumor": "ZZZT weighs a sale of its QQQX unit",
        "round_count": 2,
        "status": "complete",
    }
    app = _make_test_app()
    with TestClient(app) as client:
        app.state.app_state.graph_manager = AsyncMock(read_completed_cycles=AsyncMock(return_value=[row]))
        r = client.get("/api/replay/cycles")
    assert r.status_code == 200
    (cycle,) = r.json()["cycles"]
    fields = ("cycle_id", "created_at", "seed_rumor", "round_count")
    assert {key: cycle[key] for key in fields} == {key: row[key] for key in fields}


def test_replay_start_503_without_neo4j() -> None:
    """POST /api/replay/start/{cycle_id} returns 503 when graph_manager is None."""
    with TestClient(_make_test_app()) as client:
        r = client.post(f"/api/replay/start/{CYCLE_A}")
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
        r = client.get(f"/api/edges/{CYCLE_A}?round=1")
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
        mock_gm.read_full_cycle_signals = AsyncMock(
            return_value={
                ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
                ("agent_1", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
                ("agent_1", 3): AgentState(signal=SignalType.HOLD, confidence=0.5),
            }
        )
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app_state.graph_manager = mock_gm

        r = client.post(f"/api/replay/start/{CYCLE_A}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["cycle_id"] == CYCLE_A
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
        mock_gm.read_full_cycle_signals = AsyncMock(
            return_value={
                ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
            }
        )
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app_state.graph_manager = mock_gm

        r1 = client.post(f"/api/replay/start/{CYCLE_A}")
        assert r1.status_code == 200
        r2 = client.post(f"/api/replay/start/{CYCLE_B}")
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

        r = client.post(f"/api/replay/start/{CYCLE_UNKNOWN}")
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
        mock_gm.read_full_cycle_signals = AsyncMock(
            return_value={
                ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
                ("agent_1", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
                ("agent_1", 3): AgentState(signal=SignalType.HOLD, confidence=0.5),
            }
        )
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app.state.app_state.graph_manager = mock_gm

        client.post(f"/api/replay/start/{CYCLE_A}")
        r = client.post("/api/replay/advance")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["round_num"] == 2


def test_replay_stop_deactivates_replay() -> None:
    """POST /api/replay/stop makes replay_manager inactive. That stop leaves the live
    phase alone is pinned by tests/test_replay_live_phase.py (docs/DECISIONS.md#p34-d-10)."""
    from unittest.mock import AsyncMock

    from alphaswarm.state import AgentState
    from alphaswarm.types import SignalType

    app = _make_test_app()
    with TestClient(app) as client:
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(
            return_value={
                ("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
            }
        )
        mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
        mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
        app.state.app_state.graph_manager = mock_gm

        client.post(f"/api/replay/start/{CYCLE_A}")
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


# ---------------------------------------------------------------------------
# Quick-260416-m8x Tier 1 regression tests
# One test per fixed bug (B4 route-side, B4 sim-side, B7, B8, B9, B10).
# Each test must fail on pre-fix code and pass on post-fix code.
# ---------------------------------------------------------------------------


def test_m8x_replay_start_409_when_simulation_running() -> None:
    """B4 route-side: POST /api/replay/start returns 409 when sim is running."""
    from unittest.mock import AsyncMock

    app = _make_test_app()
    with TestClient(app) as client:
        # Provide a graph_manager so the route reaches the sim-running check.
        mock_gm = AsyncMock()
        mock_gm.read_full_cycle_signals = AsyncMock(return_value={})
        app.state.app_state.graph_manager = mock_gm

        # Flip the sim-manager into "running" state without actually running.
        client.app.state.sim_manager._is_running = True

        r = client.post(f"/api/replay/start/{CYCLE_A}")
        assert r.status_code == 409
        data = r.json()
        assert data["detail"]["error"] == "simulation_in_progress"
        assert "simulation is running" in data["detail"]["message"].lower()


async def test_m8x_sim_manager_start_raises_when_replay_active() -> None:
    """B4 sim-side: sim_manager.start() raises ReplayActiveError when replay is active."""
    from unittest.mock import MagicMock

    from alphaswarm.web.simulation_manager import ReplayActiveError

    mock_app_state = MagicMock()
    mock_replay_manager = MagicMock()
    mock_replay_manager.is_active = True
    sm = SimulationManager(mock_app_state, brackets=[], replay_manager=mock_replay_manager)

    with pytest.raises(ReplayActiveError):
        await sm.start("test seed")

    # Lock must NOT have been acquired (replay check fires before lock acquisition).
    assert not sm._lock.locked()
    assert sm._is_running is False


async def test_m8x_sim_manager_cancellation_phase_reset_before_lock_release() -> None:
    """B8: set_phase(IDLE) completes INSIDE _run (before the lock is released).

    After the fix, phase reset is awaited inside _run's except block before
    the task is marked done. The done-callback then releases the lock. So by
    the time the lock is released, set_phase(IDLE) has already been called.

    NOTE: This test asserts the correctness-preserving invariant — phase was
    IDLE before lock release — rather than trying to reproduce the race
    itself (which is probabilistic under the event loop). If direct ordering
    check proves flaky we fall back to the weaker "eventually IDLE" check.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.types import SimulationPhase

    mock_app_state = MagicMock()
    mock_state_store = MagicMock()
    mock_state_store.set_last_error = AsyncMock()
    mock_state_store.set_phase = AsyncMock()
    mock_app_state.state_store = mock_state_store
    mock_app_state.personas = []
    sm = SimulationManager(mock_app_state, brackets=[])

    # Capture lock-state at the moment the done-callback fires.
    lock_state_at_callback: list[tuple[bool, int]] = []

    original_callback = sm._on_task_done

    def capturing_callback(task: asyncio.Task[None]) -> None:
        # Record set_phase call count BEFORE the original callback releases the lock.
        lock_state_at_callback.append((sm._lock.locked(), mock_state_store.set_phase.call_count))
        original_callback(task)

    async def _long_run(**kwargs: object) -> None:
        await asyncio.sleep(100)

    mock_built = MagicMock()
    mock_built.orchestrator.aclose = AsyncMock()
    mock_built.worker.aclose = AsyncMock()
    # Patch inference factory so the test works with a MagicMock app_state.settings.
    with (
        patch("alphaswarm.inference.config.load_inference_config", return_value=MagicMock()),
        patch("alphaswarm.inference.factory.build_providers", return_value=mock_built),
        patch("alphaswarm.inference.factory.build_controller", return_value=MagicMock()),
        patch("alphaswarm.services.runtime.InferenceRuntime.run_provenance", new=AsyncMock(return_value=None)),
        patch("alphaswarm.inference.factory.inference_mode", return_value="local"),
        patch("alphaswarm.simulation.run_simulation", new=AsyncMock(side_effect=_long_run)),
    ):
        await sm.start("seed")
        # Replace the callback AFTER start has added the original, so our capturing
        # version runs instead. We must re-register on the task directly.
        assert sm._task is not None
        # Remove all existing callbacks and install ours.
        sm._task.remove_done_callback(original_callback)
        sm._task.add_done_callback(capturing_callback)

        await asyncio.sleep(0)  # let _run enter its try block
        sm.stop()
        await asyncio.sleep(0.1)

    # Invariant: at the moment the done-callback was invoked, set_phase(IDLE) was
    # already called (call_count >= 1) — meaning _run's except block completed
    # BEFORE the task was marked done and the callback fired.
    assert len(lock_state_at_callback) == 1
    lock_locked, set_phase_calls = lock_state_at_callback[0]
    assert set_phase_calls >= 1, (
        f"set_phase(IDLE) was not called before done-callback fired "
        f"(call_count={set_phase_calls}). B8 race is NOT fixed."
    )
    # Verify it was IDLE that was set.
    mock_state_store.set_phase.assert_called_with(SimulationPhase.IDLE)


async def test_m8x_replay_manager_advance_and_stop_hold_lock() -> None:
    """B9: advance() and stop() acquire self._lock exactly once per call."""
    from unittest.mock import AsyncMock, MagicMock

    from alphaswarm.state import AgentState, StateStore
    from alphaswarm.types import SignalType
    from alphaswarm.web.replay_manager import ReplayManager

    mock_app_state = MagicMock()
    # A real StateStore: start() and advance() broadcast a StateFrame built from it.
    mock_app_state.state_store = StateStore()
    rm = ReplayManager(mock_app_state)

    # Count lock acquisitions by wrapping _lock.acquire.
    acquire_counter = {"count": 0}
    original_acquire = rm._lock.acquire

    async def counting_acquire() -> bool:  # type: ignore[override]
        acquire_counter["count"] += 1
        return await original_acquire()

    rm._lock.acquire = counting_acquire  # type: ignore[method-assign]

    # Seed a minimal store + state so advance() does not early-return.
    mock_gm = AsyncMock()
    mock_gm.read_bracket_narratives_for_round = AsyncMock(return_value=[])
    mock_gm.read_rationale_entries_for_round = AsyncMock(return_value=[])
    signals = {("agent_1", 1): AgentState(signal=SignalType.BUY, confidence=0.8)}

    await rm.start("cycle-x", signals, mock_gm)
    assert acquire_counter["count"] == 1  # start() acquires once

    await rm.advance(mock_gm)
    assert acquire_counter["count"] == 2  # advance() acquires once (B9)

    await rm.stop()
    assert acquire_counter["count"] == 3  # stop() acquires once (B9)


async def test_m8x_sim_manager_complete_phase_set_once() -> None:
    """B10: set_phase(COMPLETE) is invoked exactly once per run (no manager-level duplicate).

    We simulate run_simulation calling set_phase(COMPLETE) from within
    run_simulation, then assert the manager does NOT call set_phase(COMPLETE)
    a second time after the pipeline returns.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from alphaswarm.types import SimulationPhase

    mock_app_state = MagicMock()
    mock_state_store = MagicMock()
    mock_state_store.set_last_error = AsyncMock()
    mock_state_store.set_phase = AsyncMock()
    mock_app_state.state_store = mock_state_store
    mock_app_state.personas = []
    sm = SimulationManager(mock_app_state, brackets=[])

    # Simulate run_simulation by calling set_phase(COMPLETE) from the
    # patched run_simulation, then returning successfully.
    async def _fake_pipeline(**kwargs: object) -> None:
        await mock_state_store.set_phase(SimulationPhase.COMPLETE)

    mock_built = MagicMock()
    mock_built.orchestrator.aclose = AsyncMock()
    mock_built.worker.aclose = AsyncMock()
    # Patch inference factory so the test works with a MagicMock app_state.settings.
    with (
        patch("alphaswarm.inference.config.load_inference_config", return_value=MagicMock()),
        patch("alphaswarm.inference.factory.build_providers", return_value=mock_built),
        patch("alphaswarm.inference.factory.build_controller", return_value=MagicMock()),
        patch("alphaswarm.services.runtime.InferenceRuntime.run_provenance", new=AsyncMock(return_value=None)),
        patch("alphaswarm.inference.factory.inference_mode", return_value="local"),
        patch("alphaswarm.simulation.run_simulation", new=AsyncMock(side_effect=_fake_pipeline)),
    ):
        await sm.start("seed")
        await asyncio.sleep(0.05)

    complete_calls = [
        call for call in mock_state_store.set_phase.call_args_list if call.args == (SimulationPhase.COMPLETE,)
    ]
    assert len(complete_calls) == 1, (
        f"Expected exactly one set_phase(COMPLETE) call, got {len(complete_calls)}. "
        f"B10 duplicate COMPLETE call is NOT removed. "
        f"All calls: {mock_state_store.set_phase.call_args_list}"
    )


def test_frame_memory_percent_comes_from_the_governor_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overlay shows what the governor sees (docs/DECISIONS.md#p3-d-12)."""
    import json

    from alphaswarm.state import StateStore
    from alphaswarm.web.broadcaster import snapshot_to_json

    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 23.0)
    parsed = json.loads(snapshot_to_json(StateStore()))
    assert parsed["governor_metrics"]["memory_percent"] == 23.0


def test_health_memory_percent_comes_from_the_governor_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("alphaswarm.web.routes.health.memory_used_percent", lambda: 23.0)
    with TestClient(_make_test_app()) as client:
        r = client.get("/api/health")
    assert r.json()["memory_percent"] == 23.0
