"""Retry classifier and capped full-jitter policy (docs/DECISIONS.md#adr-cloud-retry)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from alphaswarm.errors import is_permanent_http_status
from alphaswarm.inference.retry import (
    BACKOFF_CAP_S,
    DEFAULT_RETRY_POLICY,
    RetryGate,
    RetryPolicy,
    Verdict,
    classify_status,
    is_content_filter_message,
    is_context_limit_message,
    retry_after_seconds,
    wait_before_retry,
)

CONTEXT_BODIES = [
    '{"error": {"code": "context_length_exceeded", '
    '"message": "This model\'s maximum context length is 128000 tokens."}}',
    '{"type": "error", "error": {"type": "invalid_request_error", '
    '"message": "prompt is too long: 250000 tokens > 200000 maximum"}}',
    "Input exceeds the context window of this model",
]


@pytest.mark.parametrize("status", [408, 409, 500, 502, 503, 504, 529])
def test_transient_statuses_are_retried(status: int) -> None:
    assert classify_status(status) is Verdict.RETRY


def test_429_is_rate_limited() -> None:
    assert classify_status(429) is Verdict.RATE_LIMITED


@pytest.mark.parametrize("status", [401, 403])
def test_credential_statuses_are_auth(status: int) -> None:
    assert classify_status(status) is Verdict.AUTH


@pytest.mark.parametrize("status", [400, 404, 422])
def test_config_statuses_are_never_retried(status: int) -> None:
    body = '{"error": {"message": "The model `typo-model` does not exist", "code": "model_not_found"}}'
    assert classify_status(status, body) is Verdict.CONFIG


@pytest.mark.parametrize("body", CONTEXT_BODIES)
def test_context_limit_400_is_a_per_call_failure(body: str) -> None:
    """An oversized prompt is one failed call, never a stopped run."""
    assert is_context_limit_message(body)
    assert classify_status(400, body) is Verdict.FAIL


def test_content_filter_400_is_a_per_call_failure() -> None:
    body = '{"error": {"code": "content_filter", "message": "The response was filtered"}}'
    assert is_content_filter_message(body)
    assert classify_status(400, body) is Verdict.FAIL


@pytest.mark.parametrize("status", [413, 418])
def test_other_client_errors_fail_without_retry(status: int) -> None:
    assert classify_status(status) is Verdict.FAIL


def test_permanent_statuses_for_the_ollama_client() -> None:
    assert all(is_permanent_http_status(s) for s in (400, 401, 403, 404, 422))
    assert not any(is_permanent_http_status(s) for s in (408, 409, 429, 500, 503))
    assert not is_permanent_http_status(-1)  # ollama's "unknown status" keeps retrying


def test_backoff_is_capped_full_jitter() -> None:
    """No wait exceeds 30 s (the old loop slept 255 s in total at max_retries=8)."""
    top = RetryPolicy(rng=lambda: 1.0)
    assert [top.backoff_s(a) for a in range(8)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert sum(top.backoff_s(a) for a in range(8)) == 121.0
    assert RetryPolicy(rng=lambda: 0.0).backoff_s(5) == 0.0
    assert RetryPolicy(rng=lambda: 0.25).backoff_s(2) == 1.0
    assert max(DEFAULT_RETRY_POLICY.backoff_s(a) for a in range(200)) <= BACKOFF_CAP_S
    assert RetryPolicy(rng=lambda: 7.0).backoff_s(0) == 1.0  # a broken draw cannot exceed the ceiling


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7", 7.0), ("0", 0.0), ("500", 60.0), (None, None), ("", None), ("soon", None)],
)
def test_retry_after_seconds(raw: str | None, expected: float | None) -> None:
    assert retry_after_seconds(raw) == expected


def test_retry_after_http_date_is_honoured() -> None:
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    value = retry_after_seconds(when)
    assert value is not None and 0.0 <= value <= 10.0


class _Gate:
    def __init__(self) -> None:
        self.noted: list[float] = []
        self.retries = 0

    def note_rate_limited(self, seconds: float) -> None:
        self.noted.append(seconds)

    async def before_retry(self) -> None:
        self.retries += 1


def _recording_policy(slept: list[float], *, draw: float = 0.5) -> RetryPolicy:
    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    return RetryPolicy(sleep=_sleep, rng=lambda: draw)


async def test_without_a_gate_the_backoff_is_slept() -> None:
    slept: list[float] = []
    assert await wait_before_retry(_recording_policy(slept), 1, gate=None) == 1.0
    assert slept == [1.0]


async def test_retry_after_replaces_the_backoff() -> None:
    slept: list[float] = []
    await wait_before_retry(_recording_policy(slept), 3, gate=None, retry_after_s=7.0)
    assert slept == [7.0]


async def test_a_429_with_a_gate_sets_the_shared_cooldown_instead_of_sleeping() -> None:
    slept: list[float] = []
    gate = _Gate()
    delay = await wait_before_retry(_recording_policy(slept), 0, gate=gate, rate_limited=True)
    assert (slept, gate.noted, gate.retries) == ([], [delay], 1)


async def test_other_retries_with_a_gate_sleep_then_take_a_token() -> None:
    slept: list[float] = []
    gate = _Gate()
    await wait_before_retry(_recording_policy(slept), 2, gate=gate)
    assert (slept, gate.noted, gate.retries) == ([2.0], [], 1)


def test_the_gate_protocol_is_runtime_checkable() -> None:
    assert isinstance(_Gate(), RetryGate)
    assert not isinstance(object(), RetryGate)
