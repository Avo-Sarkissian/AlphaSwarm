"""Error hierarchy and the UI-safe RunError (docs/DECISIONS.md#adr-taskgroup-dispatch)."""

from __future__ import annotations

import dataclasses
import time
from decimal import Decimal

import pytest

from alphaswarm.errors import (
    INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
    INFERENCE_CONFIG_INVALID_MESSAGE,
    RUN_ERROR_MESSAGE_MAX_CHARS,
    AlphaSwarmError,
    AuthError,
    BudgetExceededError,
    GovernorCrisisError,
    GraphError,
    InferenceConfigError,
    InferenceConfigIncompleteError,
    Neo4jQueryError,
    Neo4jUnavailableError,
    Neo4jWriteError,
    RoundFailedError,
    RunError,
    run_error_from_exception,
)


def test_graph_family_shares_one_base() -> None:
    for cls in (Neo4jUnavailableError, Neo4jQueryError, Neo4jWriteError):
        assert issubclass(cls, GraphError)
        assert issubclass(cls, AlphaSwarmError)
    assert issubclass(RoundFailedError, AlphaSwarmError)
    assert issubclass(InferenceConfigError, AlphaSwarmError)
    assert issubclass(InferenceConfigIncompleteError, InferenceConfigError)


def test_existing_inference_errors_are_not_reparented() -> None:
    # Re-parenting would change which `except` clauses catch them.
    assert not issubclass(BudgetExceededError, AlphaSwarmError)
    assert not issubclass(GovernorCrisisError, AlphaSwarmError)
    assert not issubclass(AuthError, AlphaSwarmError)


def test_neo4j_write_error_keeps_baseline_positional_form() -> None:
    original = RuntimeError("driver said no")
    err = Neo4jWriteError("write failed", original)
    assert err.original_error is original
    assert err.op is None
    assert str(err) == "write failed"


def test_graph_error_records_op() -> None:
    err = Neo4jUnavailableError("down", None, op="read_latest_cycle_id")
    assert err.op == "read_latest_cycle_id"


def test_round_failed_error_carries_counts() -> None:
    err = RoundFailedError(2, 61, 100, 50.0)
    assert (err.round_num, err.failed, err.total, err.threshold_percent) == (2, 61, 100, 50.0)
    assert str(err) == "Round 2 aborted: 61 of 100 agents failed (limit 50%)"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (BudgetExceededError(Decimal("5.10"), Decimal("5.00")), "budget_exceeded"),
        (AuthError("401", provider="openai", model="fictional-model-1"), "auth_failed"),
        (GovernorCrisisError("crisis", duration_seconds=301.0), "governor_crisis"),
        (RoundFailedError(1, 100, 100, 50.0), "round_failed"),
        (Neo4jUnavailableError("down", op="persist_round"), "graph_unavailable"),
        (Neo4jQueryError("bad", op="read_round_timeline"), "graph_error"),
        (Neo4jWriteError("bad"), "graph_error"),
        (InferenceConfigError("invalid"), "inference_config_invalid"),
        (InferenceConfigIncompleteError("incomplete"), "inference_config_invalid"),
        (RuntimeError("boom"), "internal_error"),
    ],
)
def test_run_error_codes(exc: BaseException, code: str) -> None:
    err = run_error_from_exception(exc, round_num=2)
    assert err.code == code
    assert err.round_num == 2
    assert 0 < len(err.message) <= RUN_ERROR_MESSAGE_MAX_CHARS
    # No template names a file path (none of these inputs carries a slash).
    assert "/" not in err.message


def test_run_error_messages_use_structured_fields() -> None:
    budget = run_error_from_exception(
        BudgetExceededError(Decimal("5.10"), Decimal("5.00")),
        round_num=None,
    )
    assert "$5.10" in budget.message and "$5.00" in budget.message
    auth = run_error_from_exception(
        AuthError("401", provider="anthropic", model="fictional-model-2"),
        round_num=1,
    )
    assert "anthropic" in auth.message and "fictional-model-2" in auth.message
    graph = run_error_from_exception(Neo4jQueryError("x", op="read_round_timeline"), round_num=None)
    assert "read_round_timeline" in graph.message


def test_governor_crisis_message_names_the_cause() -> None:
    timeout = run_error_from_exception(
        GovernorCrisisError(
            "Governor crisis timeout after 301.0s with no successful inference",
            duration_seconds=301.0,
        ),
        round_num=2,
    )
    assert "after 301 s of sustained memory pressure" in timeout.message
    # A failed monitor loop aborts with no crisis duration; that is not memory pressure.
    dead_monitor = run_error_from_exception(
        GovernorCrisisError(
            "Memory monitor loop terminated unexpectedly: sysctl died",
            duration_seconds=0.0,
        ),
        round_num=2,
    )
    assert dead_monitor.code == "governor_crisis"
    assert "memory monitor stopped" in dead_monitor.message
    assert "pressure" not in dead_monitor.message
    assert "sysctl" not in dead_monitor.message


def test_incomplete_config_points_at_settings_not_at_the_file() -> None:
    # A config the providers reject still loads, so the health check reports it
    # ok, and moving the file aside would lose the other role's settings.
    invalid = run_error_from_exception(InferenceConfigError("x"), round_num=None)
    incomplete = run_error_from_exception(InferenceConfigIncompleteError("x"), round_num=None)
    assert invalid.message == INFERENCE_CONFIG_INVALID_MESSAGE
    assert incomplete.message == INFERENCE_CONFIG_INCOMPLETE_MESSAGE
    assert "Open Settings" in incomplete.message
    assert "move aside" not in incomplete.message
    assert "health check" not in incomplete.message


def test_unknown_exception_text_never_reaches_the_message() -> None:
    leaky = RuntimeError("open /Users/someone/.secrets/inference.json failed: sk-test-SECRET-1234")
    err = run_error_from_exception(leaky, round_num=None)
    assert err.message == "Unexpected RuntimeError. See the server log for details."
    assert "SECRET" not in err.message
    assert "/Users" not in err.message


def test_message_is_capped() -> None:
    err = run_error_from_exception(
        AuthError("401", provider="openai", model="m" * 1000),
        round_num=None,
    )
    assert len(err.message) == RUN_ERROR_MESSAGE_MAX_CHARS


def test_exception_groups_are_classified_by_their_first_leaf() -> None:
    group = ExceptionGroup(
        "outer",
        [ExceptionGroup("inner", [BudgetExceededError(Decimal("2"), Decimal("1"))])],
    )
    assert run_error_from_exception(group, round_num=3).code == "budget_exceeded"


def test_run_error_is_frozen_and_timestamped() -> None:
    before = time.time()
    err = run_error_from_exception(RuntimeError("x"), round_num=None)
    assert before <= err.ts <= time.time()
    assert isinstance(err, RunError)
    with pytest.raises(dataclasses.FrozenInstanceError):
        err.code = "auth_failed"  # type: ignore[misc]
