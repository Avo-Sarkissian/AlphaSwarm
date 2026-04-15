"""TDD RED: Failing tests for replay router (Task 1)."""

from __future__ import annotations


def test_replay_module_exists() -> None:
    """replay.py module exists and exports router."""
    from alphaswarm.web.routes.replay import router
    assert router is not None
    # Router should have 3 routes
    assert len(router.routes) == 3


def test_replay_response_models_exist() -> None:
    """Pydantic response models exist with correct fields."""
    from alphaswarm.web.routes.replay import (
        CycleItem,
        ReplayAdvanceResponse,
        ReplayCyclesResponse,
        ReplayStartResponse,
    )

    # CycleItem fields
    ci = CycleItem(cycle_id="x", created_at="2026-01-01", seed_rumor="test", round_count=3)
    assert ci.cycle_id == "x"
    assert ci.round_count == 3

    # ReplayCyclesResponse
    resp = ReplayCyclesResponse(cycles=[ci])
    assert len(resp.cycles) == 1

    # ReplayStartResponse
    start = ReplayStartResponse(status="ok", cycle_id="c1", round_num=1)
    assert start.status == "ok"

    # ReplayAdvanceResponse
    adv = ReplayAdvanceResponse(status="ok", round_num=1)
    assert adv.round_num == 1


def test_replay_cycles_endpoint_has_503_guard() -> None:
    """replay_cycles raises HTTPException 503 when graph_manager is None."""
    import asyncio
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from alphaswarm.web.routes.replay import replay_cycles

    # Create a mock request with graph_manager=None
    mock_request = MagicMock()
    mock_request.app.state.app_state.graph_manager = None

    try:
        asyncio.get_event_loop().run_until_complete(replay_cycles(mock_request))
        assert False, "Should have raised HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["error"] == "graph_unavailable"
