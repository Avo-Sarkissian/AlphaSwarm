"""InterviewEngine history rollback, role parity and block trimming."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alphaswarm.errors import AuthError
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.interview import InterviewContext, InterviewEngine
from tests.inference.fakes import FakeInferenceProvider


def _context() -> InterviewContext:
    return InterviewContext(
        agent_id="quants_01",
        agent_name="Quants 1",
        bracket="quants",
        interview_system_prompt="You are a quantitative analyst.",
        decision_narrative="Moved from BUY to HOLD.",
        decisions=[],
    )


class _Script:
    """chat() behaviour per call: True answers, False raises, 'summary' marks summary calls."""

    def __init__(self, outcomes: list[bool] | None = None, *, summary_exc: BaseException | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.summary_exc = summary_exc
        self.summary_calls = 0

    def __call__(self, **kwargs: Any) -> InferenceResult:
        messages = kwargs["messages"]
        if "summarize" in messages[0]["content"].lower():
            self.summary_calls += 1
            if self.summary_exc is not None:
                raise self.summary_exc
            return InferenceResult(content="Earlier the user asked things.", model="w")
        ok = self.outcomes.pop(0) if self.outcomes else True
        if not ok:
            raise RuntimeError("provider timeout")
        return InferenceResult(content="An answer.", model="w")


def _engine(script: _Script) -> tuple[InterviewEngine, FakeInferenceProvider]:
    provider = FakeInferenceProvider(role=ProviderRole.WORKER, model="w", scripted=script)
    return InterviewEngine(context=_context(), provider=provider), provider


def _roles(engine: InterviewEngine) -> list[str]:
    return [m["role"] for m in engine._history]


async def test_failed_turn_leaves_history_untouched() -> None:
    engine, provider = _engine(_Script([True, False, True]))
    await engine.ask("Q1")
    with pytest.raises(RuntimeError):
        await engine.ask("Q2")
    assert _roles(engine) == ["user", "assistant"]
    await engine.ask("Q3")
    sent = provider.calls[-1]["messages"]
    assert [m["role"] for m in sent[-3:]] == ["user", "assistant", "user"]
    assert sent[-1]["content"] == "Q3"
    assert _roles(engine) == ["user", "assistant", "user", "assistant"]


async def test_no_summary_until_more_than_twelve_pairs() -> None:
    script = _Script()
    engine, _ = _engine(script)
    for i in range(12):
        await engine.ask(f"Q{i}")
    assert script.summary_calls == 0
    assert len(engine._history) == 24


async def test_thirteenth_pair_summarizes_the_oldest_six_in_one_call() -> None:
    script = _Script()
    engine, provider = _engine(script)
    for i in range(13):
        await engine.ask(f"Q{i}")
    assert script.summary_calls == 1
    assert len(engine._history) == 14
    assert engine._history[0]["content"] == "Q6"
    summary_messages = provider.calls[-1]["messages"]
    assert [m["content"] for m in summary_messages if m["role"] == "user"][:6] == [f"Q{i}" for i in range(6)]
    assert engine._summary == "Earlier the user asked things."


async def test_nineteen_turns_need_two_summaries() -> None:
    script = _Script()
    engine, _ = _engine(script)
    for i in range(19):
        await engine.ask(f"Q{i}")
    assert script.summary_calls == 2
    assert len(engine._history) == 14


async def test_failed_summary_still_returns_the_answer_and_retries_later() -> None:
    script = _Script(summary_exc=RuntimeError("summary timeout"))
    engine, _ = _engine(script)
    for i in range(13):
        assert await engine.ask(f"Q{i}") == "An answer."
    assert len(engine._history) == 26
    script.summary_exc = None
    await engine.ask("Q13")
    assert len(engine._history) == 16


async def test_auth_error_during_summary_propagates() -> None:
    script = _Script(summary_exc=AuthError("bad key", provider="anthropic", model="w"))
    engine, _ = _engine(script)
    for i in range(12):
        await engine.ask(f"Q{i}")
    with pytest.raises(AuthError):
        await engine.ask("Q12")


@settings(max_examples=50, deadline=None)
@given(st.lists(st.booleans(), max_size=30))
def test_history_always_alternates_user_assistant(outcomes: list[bool]) -> None:
    async def _run() -> list[str]:
        engine, _ = _engine(_Script(list(outcomes)))
        for i in range(len(outcomes)):
            with contextlib.suppress(RuntimeError):
                await engine.ask(f"Q{i}")
        return _roles(engine)

    # A private loop on purpose: asyncio.run() would clear the thread's current event
    # loop and orphan the one pytest-asyncio installed, which then leaks and fails a
    # later test under filterwarnings = error (same pattern as test_governor_concurrency).
    loop = asyncio.new_event_loop()
    try:
        roles = loop.run_until_complete(_run())
    finally:
        loop.close()
    assert len(roles) % 2 == 0
    assert roles == ["user", "assistant"] * (len(roles) // 2)
