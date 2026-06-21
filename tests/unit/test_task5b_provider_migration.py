"""RED tests for Task 5B: advisory/report/interview engines accept InferenceProvider.

All tests here are RED until:
  - advisory/engine.py synthesize() accepts `provider: InferenceProvider` instead of
    `ollama_client` + `orchestrator_model`.
  - report.py ReportEngine.__init__ accepts `provider: InferenceProvider` instead of
    `ollama_client` + `model`.
  - interview.py InterviewEngine.__init__ accepts `provider: InferenceProvider` instead of
    `ollama_client` + `model`.
  - Each routes file builds an OllamaProvider and passes it to the engine.

pytest-socket --disable-socket is active project-wide; these tests use pure Fakes.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(content: str) -> InferenceResult:
    return InferenceResult(content=content, model="test-model")


def _valid_advisory_json(items: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "cycle_id": "c1",
            "generated_at": "2026-04-19T22:00:00+00:00",
            "portfolio_outlook": "Mildly bullish.",
            "items": items or [],
            "total_holdings": 1,
            "affected_holdings": 0,
        }
    )


def _portfolio(ticker: str = "AAPL", cost: str = "100") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker=ticker, qty=Decimal("10"), cost_basis=Decimal(cost)),),
        as_of=datetime.now(UTC),
        account_number_hash="deadbeef",
    )


class _FakeGraphManager:
    """Minimal fake graph manager for advisory tests."""

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return ""


# ---------------------------------------------------------------------------
# RED-1: Advisory engine accepts InferenceProvider
# ---------------------------------------------------------------------------


class TestAdvisoryEngineAcceptsProvider:
    """synthesize() must accept `provider: InferenceProvider` and route chat through it."""

    @pytest.mark.asyncio
    async def test_synthesize_accepts_provider_kwarg(self) -> None:
        """synthesize() must accept `provider` kwarg (InferenceProvider) — RED until migrated."""
        from alphaswarm.advisory import synthesize

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(_valid_advisory_json())],
        )
        fake_graph = _FakeGraphManager()

        # This will raise TypeError until engine.py accepts `provider`
        report = await synthesize(
            cycle_id="c1",
            portfolio=_portfolio(),
            graph_manager=fake_graph,  # type: ignore[arg-type]
            provider=fake_provider,
        )

        assert report.cycle_id == "c1"

    @pytest.mark.asyncio
    async def test_synthesize_routes_through_provider_chat(self) -> None:
        """synthesize() must call provider.chat() (not OllamaClient) — RED until migrated."""
        from alphaswarm.advisory import synthesize

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(_valid_advisory_json())],
        )
        fake_graph = _FakeGraphManager()

        await synthesize(
            cycle_id="c1",
            portfolio=_portfolio(),
            graph_manager=fake_graph,  # type: ignore[arg-type]
            provider=fake_provider,
        )

        # Provider must have been called exactly once (no retry needed for valid payload)
        assert len(fake_provider.calls) == 1

    @pytest.mark.asyncio
    async def test_synthesize_passes_json_mode_to_provider(self) -> None:
        """synthesize() must pass json_mode=True (was format='json') — RED until migrated."""
        from alphaswarm.advisory import synthesize

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(_valid_advisory_json())],
        )
        fake_graph = _FakeGraphManager()

        await synthesize(
            cycle_id="c1",
            portfolio=_portfolio(),
            graph_manager=fake_graph,  # type: ignore[arg-type]
            provider=fake_provider,
        )

        call = fake_provider.calls[0]
        # Must pass json_mode=True (format="json" migrated) OR response_schema set
        assert call.get("json_mode") is True or call.get("response_schema") is not None

    @pytest.mark.asyncio
    async def test_synthesize_retry_uses_provider(self) -> None:
        """Retry on ValidationError must also use provider.chat() — RED until migrated."""
        from alphaswarm.advisory import synthesize

        malformed = '{"cycle_id": "c1", "oops": true}'
        valid = _valid_advisory_json()

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(malformed), _make_result(valid)],
        )
        fake_graph = _FakeGraphManager()

        report = await synthesize(
            cycle_id="c1",
            portfolio=_portfolio(),
            graph_manager=fake_graph,  # type: ignore[arg-type]
            provider=fake_provider,
        )

        # Two calls: initial + retry
        assert len(fake_provider.calls) == 2
        assert report.cycle_id == "c1"


# ---------------------------------------------------------------------------
# RED-2: ReportEngine accepts InferenceProvider
# ---------------------------------------------------------------------------


class TestReportEngineAcceptsProvider:
    """ReportEngine must accept `provider: InferenceProvider` instead of ollama_client + model."""

    @pytest.mark.asyncio
    async def test_report_engine_init_with_provider(self) -> None:
        """ReportEngine(provider=..., tools=...) must work — RED until migrated."""
        from alphaswarm.report import ReportEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result("THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}")],
        )

        # This will raise TypeError until ReportEngine accepts `provider`
        engine = ReportEngine(
            provider=fake_provider,
            tools={},
        )
        assert engine is not None

    @pytest.mark.asyncio
    async def test_report_engine_routes_through_provider(self) -> None:
        """ReportEngine.run() must call provider.chat() not OllamaClient.chat() — RED."""
        from alphaswarm.report import ReportEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result("THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}")],
        )

        engine = ReportEngine(
            provider=fake_provider,
            tools={},
        )
        await engine.run("cycle1")

        assert len(fake_provider.calls) == 1

    @pytest.mark.asyncio
    async def test_report_engine_plain_chat_no_schema(self) -> None:
        """ReportEngine must use plain chat (no json_mode, no schema) — RED until migrated."""
        from alphaswarm.report import ReportEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result("THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}")],
        )

        engine = ReportEngine(
            provider=fake_provider,
            tools={},
        )
        await engine.run("cycle1")

        call = fake_provider.calls[0]
        # ReportEngine uses plain text chat — no json_mode, no schema
        assert call.get("json_mode") is False
        assert call.get("response_schema") is None


# ---------------------------------------------------------------------------
# RED-3: InterviewEngine accepts InferenceProvider
# ---------------------------------------------------------------------------


class TestInterviewEngineAcceptsProvider:
    """InterviewEngine must accept `provider: InferenceProvider` instead of ollama_client."""

    def _make_context(self) -> Any:
        from alphaswarm.interview import InterviewContext, RoundDecision

        return InterviewContext(
            agent_id="quants_01",
            agent_name="Quants 1",
            bracket="quants",
            interview_system_prompt="You are a quantitative analyst.",
            decision_narrative="Agent went bullish then cautious.",
            decisions=[
                RoundDecision(
                    round_num=1, signal="buy", confidence=0.85,
                    sentiment=0.6, rationale="Strong fundamentals",
                ),
            ],
        )

    def test_interview_engine_init_with_provider(self) -> None:
        """InterviewEngine(context=..., provider=...) must work — RED until migrated."""
        from alphaswarm.interview import InterviewEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.WORKER,
            model="test-worker",
            scripted=[_make_result("I bought because fundamentals were strong.")],
        )
        ctx = self._make_context()

        # This will raise TypeError until InterviewEngine accepts `provider`
        engine = InterviewEngine(context=ctx, provider=fake_provider)
        assert engine is not None

    @pytest.mark.asyncio
    async def test_interview_engine_routes_through_provider(self) -> None:
        """InterviewEngine.ask() must call provider.chat() — RED until migrated."""
        from alphaswarm.interview import InterviewEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.WORKER,
            model="test-worker",
            scripted=[_make_result("I bought because fundamentals were strong.")],
        )
        ctx = self._make_context()

        engine = InterviewEngine(context=ctx, provider=fake_provider)
        result = await engine.ask("Why did you buy?")

        assert result == "I bought because fundamentals were strong."
        assert len(fake_provider.calls) == 1

    @pytest.mark.asyncio
    async def test_interview_engine_plain_chat_no_schema(self) -> None:
        """InterviewEngine uses plain chat (no json_mode, no schema) — RED until migrated."""
        from alphaswarm.interview import InterviewEngine

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.WORKER,
            model="test-worker",
            scripted=[_make_result("Sure.")],
        )
        ctx = self._make_context()

        engine = InterviewEngine(context=ctx, provider=fake_provider)
        await engine.ask("Hi")

        call = fake_provider.calls[0]
        assert call.get("json_mode") is False
        assert call.get("response_schema") is None

    @pytest.mark.asyncio
    async def test_interview_engine_sliding_window_uses_provider(self) -> None:
        """Window trim summary generation must also use provider.chat() — RED until migrated."""
        from alphaswarm.interview import InterviewEngine

        # 11 ask responses + 1 summary = 12 total
        scripted = [_make_result("Response") for _ in range(12)]
        fake_provider = FakeInferenceProvider(
            role=ProviderRole.WORKER,
            model="test-worker",
            scripted=scripted,
        )
        ctx = self._make_context()

        engine = InterviewEngine(context=ctx, provider=fake_provider)
        for i in range(11):
            await engine.ask(f"Question {i}")

        # 11 ask calls + 1 summary generation = 12 provider calls
        assert len(fake_provider.calls) == 12


# ---------------------------------------------------------------------------
# RED-4: _run_advisory_synthesis uses build_providers
# ---------------------------------------------------------------------------


class TestAdvisoryRouteBuildsProvider:
    """_run_advisory_synthesis must use build_providers and call provider.prepare/teardown."""

    @pytest.mark.asyncio
    async def test_run_advisory_calls_provider_prepare_and_teardown(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_run_advisory_synthesis must call provider.prepare() and provider.teardown()
        via the build_providers seam (honours InferenceConfig, not hardcoded Ollama)."""
        from unittest.mock import patch

        import alphaswarm.web.routes.advisory as advisory_module

        prepare_called: list[bool] = []
        teardown_called: list[bool] = []

        class _FakeProvider:
            role = ProviderRole.ORCHESTRATOR
            model = "orch"

            async def prepare(self) -> None:
                prepare_called.append(True)

            async def teardown(self) -> None:
                teardown_called.append(True)

            async def aclose(self) -> None:
                pass

            async def chat(self, messages: Any, **kwargs: Any) -> InferenceResult:
                return _make_result(_valid_advisory_json())

        from alphaswarm.inference.budget import BudgetMeter
        from alphaswarm.inference.factory import BuiltProviders

        fake_provider = _FakeProvider()
        fake_built = BuiltProviders(
            orchestrator=fake_provider,  # type: ignore[arg-type]
            worker=fake_provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        )

        from datetime import UTC, datetime
        from decimal import Decimal
        from types import SimpleNamespace

        from alphaswarm.holdings.types import Holding, PortfolioSnapshot

        portfolio = PortfolioSnapshot(
            holdings=(Holding(ticker="AAPL", qty=Decimal("10"), cost_basis=Decimal("100")),),
            as_of=datetime.now(UTC),
            account_number_hash="deadbeef",
        )

        app_state = SimpleNamespace(
            settings=MagicMock(),
            graph_manager=_FakeGraphManager(),
            ollama_client=MagicMock(),
            model_manager=AsyncMock(),
        )

        with patch.object(advisory_module, "build_providers", return_value=fake_built), \
                patch.object(advisory_module, "load_inference_config", return_value=MagicMock()):
            await advisory_module._run_advisory_synthesis(app_state, "c1", portfolio)  # type: ignore[arg-type]

        assert prepare_called == [True], "provider.prepare() not called"
        assert teardown_called == [True], "provider.teardown() not called in finally"


# ---------------------------------------------------------------------------
# RED-5: _run_report_generation uses build_providers
# ---------------------------------------------------------------------------


class TestReportRouteBuildsProvider:
    """_run_report_generation must use build_providers and call provider.prepare/teardown."""

    @pytest.mark.asyncio
    async def test_run_report_calls_provider_prepare_and_teardown(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_run_report_generation must call provider.prepare() and provider.teardown()
        via the build_providers seam (honours InferenceConfig, not hardcoded Ollama)."""
        from unittest.mock import patch

        import alphaswarm.web.routes.report as report_module

        monkeypatch.chdir(tmp_path)

        prepare_called: list[bool] = []
        teardown_called: list[bool] = []

        class _FakeProvider:
            role = ProviderRole.ORCHESTRATOR
            model = "orch"

            async def prepare(self) -> None:
                prepare_called.append(True)

            async def teardown(self) -> None:
                teardown_called.append(True)

            async def aclose(self) -> None:
                pass

            async def chat(self, messages: Any, **kwargs: Any) -> InferenceResult:
                return _make_result("THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}")

        from alphaswarm.inference.budget import BudgetMeter
        from alphaswarm.inference.factory import BuiltProviders

        fake_provider = _FakeProvider()
        fake_built = BuiltProviders(
            orchestrator=fake_provider,  # type: ignore[arg-type]
            worker=fake_provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        )

        from types import SimpleNamespace
        app_state = SimpleNamespace(
            settings=MagicMock(),
            graph_manager=AsyncMock(),
            ollama_client=MagicMock(),
            model_manager=AsyncMock(),
        )
        app_state.graph_manager.read_shock_event = AsyncMock(return_value=None)

        with patch.object(report_module, "build_providers", return_value=fake_built), \
                patch.object(report_module, "load_inference_config", return_value=MagicMock()):
            await report_module._run_report_generation(app_state, "c1")  # type: ignore[arg-type]

        assert prepare_called == [True], "provider.prepare() not called"
        assert teardown_called == [True], "provider.teardown() not called in finally"
