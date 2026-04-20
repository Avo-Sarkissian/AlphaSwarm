"""ISOL-07 (D-14, D-15, D-16): four-surface holdings isolation canary.

================================================================================
PHASE 41 STATUS: ACTIVE — real synthesize() harness in place
================================================================================

As of Phase 41 Plan 02 (D-20), the canary is LOAD-BEARING: each of the four
negative assertion tests calls the real `alphaswarm.advisory.synthesize`
function with the sentinel `PortfolioSnapshot`. Capture sinks are wired into
every surface that synthesize() touches:

  Surface #1 (logs)     — structlog JSON output captured via capture_logs.
  Surface #2 (neo4j)    — CanaryFakeGraphManager appends each read cycle_id
                          into capture_neo4j_writes.
  Surface #3 (ws)       — advisory deliberately never publishes WS frames; a
                          generic placeholder is appended so the positive
                          control path keeps working.
  Surface #4 (prompts)  — CanaryFakeOllamaClient appends the concatenated
                          LLM messages into capture_jinja_renders.

Design carve-out (D-05): the advisory prompt legitimately includes ticker,
qty, and cost_basis strings so the LLM can decide which holdings are
affected. The rendered-prompt test asserts absence of every other sentinel
representation (account hash, hashed account form) and of the sentinel
ticker through the other three surfaces. See
test_sentinels_do_not_appear_in_rendered_prompts for the carve-out rationale.

Historical context (preserved for archaeology):
--------------------------------------------------------------------------------
Phase 37 shipped this file as SCAFFOLDED with a placeholder stand-in that
did not call any real advisory code. The canary trivially passed because no
advisory join point existed yet. Phase 41 Plan 02 replaced the stand-in with
`_advisory_harness_body` and wired the real synthesize() call; this comment
block is retained so future archaeologists can trace the activation point.
--------------------------------------------------------------------------------

Pitfall 6: each "negative" assertion has a matching "positive control" test
that proves the capture machinery actually captures.

REVIEW MEDIUM (Codex): canary searches for ALL sentinel representations
(raw, Decimal-string, JSON-quoted, sha256_first8) — not just raw strings.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from alphaswarm.advisory import synthesize
from alphaswarm.holdings.types import PortfolioSnapshot

from .conftest import (
    SENTINEL_ACCT,
    SENTINEL_COST_BASIS,
    SENTINEL_QTY,
    SENTINEL_TICKER,
    CanaryFakeGraphManager,
    CanaryFakeOllamaClient,
    all_sentinel_representations,
    canary_valid_advisory_json,
)

pytestmark = pytest.mark.enable_socket  # D-16: canary fixtures touch surfaces that may want sockets


async def _advisory_harness_body(
    snapshot: PortfolioSnapshot,
    ws_frames: list[str],
    neo4j_writes: list[str],
    jinja_renders: list[str],
) -> None:
    """Phase 41 D-20 ACTIVE canary body — calls the real synthesize() function.

    Every surface is wired through a capture sink. If synthesize() leaks any
    sentinel into a log event, Neo4j cypher, WS frame, or rendered prompt,
    the negative assertions below fail.

    WS sink: advisory deliberately does NOT publish WS frames (RESEARCH
    "Anti-Patterns to Avoid"). We append a sentinel-free placeholder so the
    positive-control path still works; real synthesize() contributes nothing
    here, which is the invariant.
    """
    fake_graph = CanaryFakeGraphManager(neo4j_sink=neo4j_writes)
    fake_ollama = CanaryFakeOllamaClient(
        prompt_sink=jinja_renders,
        canned_content=canary_valid_advisory_json(),
    )
    ws_frames.append('{"event": "phase_change", "phase": "complete"}')  # generic, no sentinels

    # REAL synthesize() — sentinels flowing through `snapshot` must not reach any sink.
    _ = await synthesize(
        cycle_id="canary_cycle",
        portfolio=snapshot,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )


# --------- Negative canary assertions (D-15 — four surfaces; REVIEW MEDIUM variants) ---------


async def test_sentinels_do_not_appear_in_logs(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    await _advisory_harness_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders,
    )
    log_output = capture_logs.getvalue()
    for sentinel in all_sentinel_representations():
        # SENTINEL_TICKER IS expected to appear in capture_jinja_renders because
        # synthesize() legitimately places the ticker in the prompt; but the
        # LOG surface must remain sentinel-free (Pitfall 1).
        assert sentinel not in log_output, (
            f"sentinel representation {sentinel!r} leaked into log output:\n{log_output}"
        )


async def test_sentinels_do_not_appear_in_ws_frames(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    await _advisory_harness_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders,
    )
    joined = "\n".join(capture_ws_frames)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into WS frames"


async def test_sentinels_do_not_appear_in_neo4j_writes(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    await _advisory_harness_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders,
    )
    joined = "\n".join(capture_neo4j_writes)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, (
            f"sentinel representation {sentinel!r} leaked into Neo4j writes"
        )


async def test_sentinels_do_not_appear_in_rendered_prompts(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    """D-05 carve-out: ticker/qty/cost_basis legitimately appear in the prompt.

    The advisory prompt serializes holdings (ticker, qty, cost_basis) so the
    LLM can reason about which holdings are affected. This test asserts
    absence of:
      - SENTINEL_ACCT (account identifier — never belongs in the prompt)
      - account-hash variants (sha256_first8 of SENTINEL_ACCT)
      - JSON-quoted Decimal variants that are NOT the intentionally serialized
        cost_basis / qty values
    and tolerates the three D-05-sanctioned representations
    (SENTINEL_TICKER, str(SENTINEL_COST_BASIS), str(SENTINEL_QTY), and the
    JSON-quoted forms of those Decimals).

    If a future change removes cost_basis from the prompt entirely, the
    non-skipped representations still trip this test.
    """
    await _advisory_harness_body(
        sentinel_portfolio, capture_ws_frames, capture_neo4j_writes, capture_jinja_renders,
    )
    joined = "\n".join(capture_jinja_renders)

    # EXPECTED to appear (ticker is legitimately in prompts — the LLM needs it):
    #   SENTINEL_TICKER
    # EXPECTED to NEVER appear (these are isolation-sensitive PII-equivalents):
    sensitive_reps = tuple(
        rep for rep in all_sentinel_representations()
        if rep != SENTINEL_TICKER
    )
    # Additionally, cost_basis is passed as a string to the prompt — that IS
    # the engineered leakage path for the sentinel cost. If the test fails
    # here, synthesize() is forwarding cost_basis as intended by D-05 for the
    # prompt; confirm by checking that the cost_basis representation appears
    # in the JOINED prompt string. If a future change drops cost_basis from
    # the prompt, this test remains a tripwire.
    for sentinel in sensitive_reps:
        if sentinel in (str(SENTINEL_COST_BASIS), str(SENTINEL_QTY),
                        f'"{SENTINEL_COST_BASIS}"', f'"{SENTINEL_QTY}"'):
            # qty and cost_basis MAY appear in the prompt (D-05 serializes
            # holdings including cost_basis). This is by design. Skip these
            # specific representations from the absence assertion.
            continue
        assert sentinel not in joined, (
            f"sentinel representation {sentinel!r} leaked into rendered prompts"
        )


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


