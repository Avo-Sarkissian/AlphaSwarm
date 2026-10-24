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

Design carve-out (docs/DECISIONS.md#p41-d-05): the advisory prompt includes the
held ticker and nothing else about a position, so the LLM can decide which
holdings are affected. The rendered-prompt test asserts that quantity, cost basis
and every account representation are absent; the other three surfaces must not
carry even the ticker.

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

import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog
from fastapi.testclient import TestClient

from alphaswarm.advisory import synthesize
from alphaswarm.holdings.types import PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from tests.support.web_app import CYCLE_A, FakeCycleGraph, block_service_jobs, make_route_app, route_test_settings

from .conftest import (
    CANARY_EVIDENCE_AGENT_IDS,
    SENTINEL_ACCT,
    SENTINEL_COST_BASIS,
    SENTINEL_QTY,
    SENTINEL_TICKER,
    CanaryFakeGraphManager,
    CanaryFakeOllamaClient,
    CanarySequenceProvider,
    all_sentinel_representations,
    canary_invalid_advisory_json,
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
    fake_provider = CanaryFakeOllamaClient(
        prompt_sink=jinja_renders,
        canned_content=canary_valid_advisory_json(),
    )
    ws_frames.append('{"event": "phase_change", "phase": "complete"}')  # generic, no sentinels

    # REAL synthesize() — sentinels flowing through `snapshot` must not reach any sink.
    _ = await synthesize(
        cycle_id="canary_cycle",
        portfolio=snapshot,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,  # type: ignore[arg-type]
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
        sentinel_portfolio,
        capture_ws_frames,
        capture_neo4j_writes,
        capture_jinja_renders,
    )
    log_output = capture_logs.getvalue()
    for sentinel in all_sentinel_representations():
        # SENTINEL_TICKER IS expected to appear in capture_jinja_renders because
        # synthesize() legitimately places the ticker in the prompt; but the
        # LOG surface must remain sentinel-free (Pitfall 1).
        assert sentinel not in log_output, f"sentinel representation {sentinel!r} leaked into log output:\n{log_output}"


async def test_sentinels_do_not_appear_in_ws_frames(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    await _advisory_harness_body(
        sentinel_portfolio,
        capture_ws_frames,
        capture_neo4j_writes,
        capture_jinja_renders,
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
        sentinel_portfolio,
        capture_ws_frames,
        capture_neo4j_writes,
        capture_jinja_renders,
    )
    joined = "\n".join(capture_neo4j_writes)
    for sentinel in all_sentinel_representations():
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into Neo4j writes"


async def test_sentinels_do_not_appear_in_rendered_prompts(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_ws_frames: list[str],
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    """Only the ticker may reach the advisory prompt (docs/DECISIONS.md#p41-d-05).

    Quantity, cost basis and every account representation must be absent: the
    ticker is the one sanctioned holdings value in any prompt.
    """
    await _advisory_harness_body(
        sentinel_portfolio,
        capture_ws_frames,
        capture_neo4j_writes,
        capture_jinja_renders,
    )
    joined = "\n".join(capture_jinja_renders)
    assert SENTINEL_TICKER in joined  # positive control: the prompt was captured
    for sentinel in all_sentinel_representations():
        if sentinel == SENTINEL_TICKER:
            continue
        assert sentinel not in joined, f"sentinel representation {sentinel!r} leaked into rendered prompts"


async def test_swarm_evidence_reaches_the_report_but_no_prompt_or_log(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
) -> None:
    """Per-holding swarm evidence is joined after the LLM call: it is in the advisory
    the route serves, and in no prompt or log (docs/DECISIONS.md#adr-grounded-advisory)."""
    report = await synthesize(
        cycle_id="canary_cycle",
        portfolio=sentinel_portfolio,
        graph_manager=CanaryFakeGraphManager(neo4j_sink=capture_neo4j_writes),  # type: ignore[arg-type]
        provider=CanaryFakeOllamaClient(  # type: ignore[arg-type]
            prompt_sink=capture_jinja_renders, canned_content=canary_valid_advisory_json()
        ),
    )
    item = next(i for i in report.items if i.ticker == SENTINEL_TICKER)
    # Positive control: the evidence join ran.
    assert (item.swarm_support, item.swarm_signal) == (3, "BUY")
    assert item.evidence_agent_ids == CANARY_EVIDENCE_AGENT_IDS
    prompts = "\n".join(capture_jinja_renders)
    logs = capture_logs.getvalue()
    for agent_id in CANARY_EVIDENCE_AGENT_IDS:
        assert agent_id not in prompts, f"evidence agent id {agent_id!r} leaked into the prompt"
        assert agent_id not in logs, f"evidence agent id {agent_id!r} leaked into a log line"
    for sentinel in all_sentinel_representations():
        assert sentinel not in logs, f"sentinel representation {sentinel!r} leaked into log output"
        if sentinel != SENTINEL_TICKER:
            assert sentinel not in prompts, f"sentinel representation {sentinel!r} leaked into the prompt"


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


# --------- Failure path: invalid LLM JSON must not leak through errors ---------


def _fresh_advisory_loggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the advisory loggers at fresh proxies so capture_logs sees them even
    when an earlier test cached them under another structlog configuration."""
    import alphaswarm.advisory.engine as engine_module
    import alphaswarm.inference.structured as structured_module
    import alphaswarm.services.advisory as advisory_service
    import alphaswarm.services.jobs as jobs_module
    import alphaswarm.web.routes.advisory as advisory_route

    monkeypatch.setattr(engine_module, "log", structlog.get_logger(component="advisory"))
    monkeypatch.setattr(structured_module, "log", structlog.get_logger(component="inference.structured"))
    monkeypatch.setattr(advisory_route, "log", structlog.get_logger(component="web.advisory"))
    monkeypatch.setattr(advisory_service, "log", structlog.get_logger(component="services.advisory"))
    monkeypatch.setattr(jobs_module, "log", structlog.get_logger(component="services.jobs"))


async def test_invalid_first_response_leaks_nothing(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry warning and the retry prompt carry no holdings values."""
    _fresh_advisory_loggers(monkeypatch)
    provider = CanarySequenceProvider(
        prompt_sink=capture_jinja_renders,
        contents=[canary_invalid_advisory_json(), canary_valid_advisory_json()],
    )
    await synthesize(
        cycle_id="canary_cycle",
        portfolio=sentinel_portfolio,
        graph_manager=CanaryFakeGraphManager(neo4j_sink=capture_neo4j_writes),  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
    )
    log_output = capture_logs.getvalue()
    retry_prompt = capture_jinja_renders[1]
    assert "structured_output_invalid" in log_output  # positive control: the retry was logged
    # positive control: the retry prompt was captured
    assert "did not match the required JSON schema" in retry_prompt
    for sentinel in all_sentinel_representations():
        assert sentinel not in log_output, f"sentinel representation {sentinel!r} leaked into logs"
        if sentinel != SENTINEL_TICKER:
            assert sentinel not in retry_prompt, f"{sentinel!r} echoed into the retry prompt"


def test_invalid_twice_leaks_nothing_to_logs_or_http(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    capture_neo4j_writes: list[str],
    capture_jinja_renders: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """End to end: POST, the job fails twice, GET answers 500 without holdings."""
    import alphaswarm.web.routes.advisory as advisory_route

    _fresh_advisory_loggers(monkeypatch)
    provider = CanarySequenceProvider(
        prompt_sink=capture_jinja_renders,
        contents=[canary_invalid_advisory_json(), canary_invalid_advisory_json()],
    )
    monkeypatch.setattr(
        "alphaswarm.inference.factory.build_providers",
        lambda *_a, **_k: BuiltProviders(
            orchestrator=provider,  # type: ignore[arg-type]
            worker=provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        ),
    )

    class _Graph(CanaryFakeGraphManager):
        async def read_cycle_status(self, cycle_id: str) -> str | None:
            return "complete" if cycle_id == CYCLE_A else None

        async def read_cycle_seed(self, cycle_id: str) -> str:
            return ""

    app = make_route_app(
        advisory_route.router,
        settings=route_test_settings(tmp_path),
        graph=_Graph(neo4j_sink=capture_neo4j_writes),
        portfolio=sentinel_portfolio,
    )
    with TestClient(app) as client:
        # The job asks Ollama whether the orchestrator runs locally; answer "local".
        app.state.app_state.ollama_client.is_remote_model = AsyncMock(return_value=False)
        assert client.post(f"/api/advisory/{CYCLE_A}").status_code == 202
        response = client.get(f"/api/advisory/{CYCLE_A}")
        for _ in range(200):  # 409 while the job runs; each request yields to the loop
            if response.status_code != 409:
                break
            response = client.get(f"/api/advisory/{CYCLE_A}")
    assert response.status_code == 500
    assert response.json()["detail"]["message"] == "Advisory generation failed; see the server log"
    log_output = capture_logs.getvalue()
    assert "advisory_generation_failed" in log_output  # positive control
    for sentinel in all_sentinel_representations():
        assert sentinel not in response.text, f"{sentinel!r} leaked into the HTTP body"
        assert sentinel not in log_output, f"{sentinel!r} leaked into logs"


# --------- AppState (reachable from the swarm side) never holds the portfolio ---------


def test_holdings_never_land_on_app_state(
    sentinel_portfolio: PortfolioSnapshot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """The portfolio stays in app.state.portfolio_cache, never on the shared AppState
    (docs/DECISIONS.md#adr-holdings-isolation)."""
    import alphaswarm.web.routes.advisory as advisory_route

    block_service_jobs(monkeypatch)
    app = make_route_app(
        advisory_route.router,
        settings=route_test_settings(tmp_path),
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=sentinel_portfolio,
    )
    with TestClient(app) as client:
        assert client.post(f"/api/advisory/{CYCLE_A}").status_code == 202
        app_state = app.state.app_state
        assert not any(isinstance(value, PortfolioSnapshot) for value in vars(app_state).values())
        assert not hasattr(app_state, "portfolio_snapshot")


def test_no_source_assigns_a_portfolio_snapshot_attribute() -> None:
    """Source scan: the lazy reload that wrote AppState.portfolio_snapshot stays deleted."""
    src = Path(__file__).resolve().parents[2] / "src" / "alphaswarm"
    hits = [
        f"{path.relative_to(src)}:{number}"
        for path in sorted(src.rglob("*.py"))
        if not re.search(r" [2-9]\.py$", path.name)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"\bportfolio_snapshot\b", line)
    ]
    assert hits == [], f"portfolio_snapshot reappeared at {hits}"


async def test_advisory_service_logs_carry_no_sentinels(
    sentinel_portfolio: PortfolioSnapshot,
    capture_logs: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service layer adds logging and a file write around synthesize(): its logs stay clean."""
    from typing import cast

    import alphaswarm.services.advisory as advisory_service
    from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig
    from alphaswarm.services.advisory import AdvisoryService
    from alphaswarm.services.jobs import JobRunner
    from alphaswarm.services.runtime import InferenceRuntime
    from alphaswarm.state import StateStore

    _fresh_advisory_loggers(monkeypatch)
    monkeypatch.setattr(advisory_service, "log", structlog.get_logger(component="services.advisory"))
    prompts: list[str] = []
    provider = CanaryFakeOllamaClient(prompt_sink=prompts, canned_content=canary_valid_advisory_json())

    class _LocalOllama:
        base_url = "http://127.0.0.1:11434"

        async def is_remote_model(self, model: str) -> bool:
            return False

    class _Inference:
        ollama_client = _LocalOllama()

        async def config(self) -> InferenceConfig:
            return InferenceConfig(
                orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="o"),
                worker=RoleConfig(provider=ProviderType.OLLAMA, model="w"),
            )

        async def open_operation(self, name: str) -> BuiltProviders:
            return BuiltProviders(orchestrator=provider, worker=provider, budget_meter=BudgetMeter(None, {}))  # type: ignore[arg-type]

    async def _portfolio() -> PortfolioSnapshot:
        return sentinel_portfolio

    service = AdvisoryService(
        graph=CanaryFakeGraphManager(neo4j_sink=[]),  # type: ignore[arg-type]
        inference=cast(InferenceRuntime, _Inference()),
        jobs=JobRunner(StateStore()),
        advisory_dir=tmp_path,
        portfolio=_portfolio,
    )
    assert await service.gate("canary_cycle") == "run"
    await service.generate("canary_cycle")
    log_output = capture_logs.getvalue()
    assert "advisory_written" in log_output  # positive control: the service logs were captured
    for sentinel in all_sentinel_representations():
        assert sentinel not in log_output, f"{sentinel!r} leaked into service logs"
