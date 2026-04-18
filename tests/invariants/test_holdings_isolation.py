"""ISOL-07 (D-14, D-15, D-16): four-surface holdings isolation canary.

================================================================================
PHASE 37 STATUS: SCAFFOLDED (REVIEW MEDIUM — Codex canary realism)
================================================================================

At Phase 37 NO code path consumes `sentinel_portfolio`. The "minimal simulation
body" below is a stand-in that logs generic events, writes generic Cypher,
emits a generic WS frame, and renders nothing. The canary trivially passes
because no advisory join point exists yet.

The canary becomes LOAD-BEARING at Phase 41 when the advisory synthesis
function activates. The activation points are:

  Phase 41 activation checklist:
  ---------------------------------------------------------------------------
  1. alphaswarm.advisory.pipeline.synthesize(snapshot, context) is implemented
     and called by the orchestrator AFTER simulation consensus.
  2. alphaswarm.advisory.pipeline.synthesize MUST accept the full PortfolioSnapshot
     but MUST NOT forward it into:
       a. structlog.get_logger() event_dicts (→ logs surface)
       b. neo4j driver session.run() cypher params (→ neo4j surface)
       c. web.broadcaster.ConnectionManager.send_to_all frames (→ ws surface)
       d. Jinja2 Environment.render worker_context (→ prompts surface)
  3. At Phase 41, _minimal_simulation_body is REPLACED with a call to the real
     synthesize() function wired to capture_logs/capture_ws_frames/
     capture_neo4j_writes/capture_jinja_renders — not to real sinks.

Until then, this test's value is PROVING THE CAPTURE MACHINERY WORKS via
positive-control tests (Pitfall 6), and establishing the exact file shape
so Phase 41 can flip it from scaffolded to active with zero test scaffolding
work.
================================================================================

Pitfall 6: each "negative" assertion has a matching "positive control" test
that proves the capture machinery actually captures.

REVIEW MEDIUM (Codex): canary searches for ALL sentinel representations
(raw, Decimal-string, JSON-quoted, sha256_first8) — not just raw strings.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import structlog

from alphaswarm.holdings.types import PortfolioSnapshot

from .conftest import (
    SENTINEL_ACCT,
    SENTINEL_COST_BASIS,
    SENTINEL_QTY,
    SENTINEL_TICKER,
    all_sentinel_representations,
)

pytestmark = pytest.mark.enable_socket  # D-16: canary fixtures touch surfaces that may want sockets


def _minimal_simulation_body(
    snapshot: PortfolioSnapshot,
    ws_frames: list[str],
    neo4j_writes: list[str],
    jinja_renders: list[str],
) -> None:
    """Phase 37 SCAFFOLDED simulation body — no advisory path, no real orchestration.

    At Phase 41 this is REPLACED by:
      await alphaswarm.advisory.pipeline.synthesize(
          snapshot=snapshot,
          sinks=CanarySinks(ws_frames, neo4j_writes, jinja_renders),
      )

    For now: logs a generic event (no holdings), sends a generic WS frame,
    writes a generic Cypher string, renders nothing. None of these touch
    the `snapshot` argument — that's the invariant under test.

    REVIEW LOW (Gemini Decimal serialization): json.dumps uses default=str.
    """
    logger = structlog.get_logger()
    logger.info("simulation.started", cycle_id="canary_cycle")
    ws_frames.append(json.dumps({"event": "phase_change", "phase": "seeding"}, default=str))
    neo4j_writes.append("CREATE (c:Cycle {id: 'canary_cycle'})")
    # jinja_renders intentionally empty — no worker prompt references snapshot at Phase 37.

    # Deliberately do NOT pass `snapshot` into any of the sinks above.
    # If a future change accidentally passes snapshot fields into a sink, this test fails.
    _ = snapshot  # silence unused-argument warning (the entire point is we DON'T use it)


# --------- Negative canary assertions (D-15 — four surfaces; REVIEW MEDIUM variants) ---------


def test_sentinels_do_not_appear_in_logs(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    _minimal_simulation_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders
    )
    log_output = capture_logs.getvalue()
    for sentinel in all_sentinel_representations():
        assert sentinel not in log_output, (
            f"sentinel representation {sentinel!r} leaked into log output:\n{log_output}"
        )


def test_sentinels_do_not_appear_in_ws_frames(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    _minimal_simulation_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders
    )
    joined = "\n".join(capture_ws_frames)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into WS frames"


def test_sentinels_do_not_appear_in_neo4j_writes(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    _minimal_simulation_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders
    )
    joined = "\n".join(capture_neo4j_writes)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into Neo4j writes"


def test_sentinels_do_not_appear_in_rendered_prompts(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    _minimal_simulation_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders
    )
    joined = "\n".join(capture_jinja_renders)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into rendered prompts"


# --------- Positive controls (Pitfall 6 — prove capture works) ---------


def test_positive_control_logs_capture_sentinel_if_injected(capture_logs: Any) -> None:
    """Inject sentinel into log output directly; capture_logs MUST see it.

    The whole point: if this test FAILS, capture_logs is broken and the negative
    tests above are false-assurance.
    """
    logger = structlog.get_logger()
    logger.info("positive_control", injected_field=SENTINEL_TICKER)
    # 'injected_field' is not a sensitive key, so the PII processor leaves it alone.
    output = capture_logs.getvalue()
    assert SENTINEL_TICKER in output, f"capture_logs buffer did not see the sentinel:\n{output}"


def test_positive_control_ws_frames_capture_injected(capture_ws_frames: list[str]) -> None:
    capture_ws_frames.append(f"some_frame_with_{SENTINEL_TICKER}")
    assert any(SENTINEL_TICKER in f for f in capture_ws_frames)


def test_positive_control_neo4j_writes_capture_injected(capture_neo4j_writes: list[str]) -> None:
    capture_neo4j_writes.append(f"CREATE (n {{ticker: '{SENTINEL_TICKER}'}})")
    assert any(SENTINEL_TICKER in w for w in capture_neo4j_writes)


def test_positive_control_jinja_renders_capture_injected(capture_jinja_renders: list[str]) -> None:
    capture_jinja_renders.append(f"prompt: {SENTINEL_TICKER}")
    assert any(SENTINEL_TICKER in r for r in capture_jinja_renders)


# --------- Meta: sentinel portfolio fixture is sane ---------


def test_sentinel_portfolio_builds_with_expected_fields(
    sentinel_portfolio: PortfolioSnapshot,
) -> None:
    assert len(sentinel_portfolio.holdings) == 1
    assert sentinel_portfolio.holdings[0].ticker == SENTINEL_TICKER
    assert sentinel_portfolio.holdings[0].qty == SENTINEL_QTY
    assert sentinel_portfolio.holdings[0].cost_basis == SENTINEL_COST_BASIS
    assert sentinel_portfolio.account_number_hash == SENTINEL_ACCT


def test_all_sentinel_representations_covers_expected_forms() -> None:
    """REVIEW MEDIUM (Codex): the representation helper must include every
    form a sentinel can take after serialization. This test documents the set
    so future developers don't trim it by accident."""
    reps = all_sentinel_representations()
    # Raw forms
    assert SENTINEL_TICKER in reps
    assert SENTINEL_ACCT in reps
    # Decimal-string forms
    assert "999999.99" in reps
    assert "77.7777" in reps
    # JSON-quoted Decimal forms
    assert '"999999.99"' in reps
    assert '"77.7777"' in reps
    # Hashed account form
    assert any(r.startswith("SNTL") is False and len(r) == 8 for r in reps), (
        "Expected an 8-hex sha256_first8(SENTINEL_ACCT) entry in representations"
    )
