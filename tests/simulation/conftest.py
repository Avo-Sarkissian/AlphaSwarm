"""Fixtures shared by the tests/simulation/ modules."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.settings import AppSettings
from tests.support.graph_fakes import fake_persist_round


@pytest.fixture()
def mock_settings() -> AppSettings:
    """AppSettings with no .env influence."""
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture()
def mock_ollama_client() -> MagicMock:
    """Mock OllamaClient (only passed through to providers in these tests)."""
    return MagicMock()


@pytest.fixture()
def mock_model_manager() -> AsyncMock:
    """Mock OllamaModelManager with load_model, unload_model, ensure_clean_state."""
    mm = AsyncMock()
    mm.load_model = AsyncMock()
    mm.unload_model = AsyncMock()
    mm.ensure_clean_state = AsyncMock()
    return mm


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    """Mock GraphStateManager with persist_round and compute_influence_edges."""
    gm = AsyncMock()
    gm.persist_round = AsyncMock(side_effect=fake_persist_round)  # one transaction per round
    gm.set_cycle_status = AsyncMock()
    gm.compute_influence_edges = AsyncMock(return_value={})
    gm.read_cycle_entities = AsyncMock(return_value=[])  # Phase 11
    # Phase 35.1 — shock injection writer (B1 wiring fix)
    gm.write_shock_event = AsyncMock(return_value="shock-id-123")
    return gm


@pytest.fixture()
def mock_governor() -> AsyncMock:
    """Mock ResourceGovernor with start_monitoring and stop_monitoring.

    release() and report_wave_failures() are SYNC on the real ResourceGovernor,
    so they are set as MagicMock (not AsyncMock) to avoid "coroutine never
    awaited" RuntimeWarnings when the sim loop calls governor.release(...).
    """
    gov = AsyncMock()
    gov.start_monitoring = AsyncMock()
    gov.stop_monitoring = AsyncMock()
    gov.release = MagicMock()
    gov.report_wave_failures = MagicMock()
    return gov
