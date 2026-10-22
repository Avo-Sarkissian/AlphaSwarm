"""Peer selection, exposure and provenance (docs/DECISIONS.md#adr-diverse-peer-context)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pytest

from alphaswarm.config import DEFAULT_BRACKETS, SimulationSettings, generate_personas
from alphaswarm.inference.types import ProviderRole
from alphaswarm.simulation import (
    _build_diverse_peer_contexts,
    _peer_and_provenance_metrics,
    compute_exposure_metrics,
)
from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SignalType
from tests.inference.fakes import FakeInferenceProvider


def _persona(agent_id: str, bracket: BracketType, weight: float = 0.5) -> AgentPersona:
    return AgentPersona(
        id=agent_id,
        name=agent_id,
        bracket=bracket,
        risk_profile=0.5,
        temperature=0.5,
        system_prompt="t",
        influence_weight_base=weight,
    )


FIVE_BRACKETS = (
    BracketType.QUANTS,
    BracketType.DEGENS,
    BracketType.MACRO,
    BracketType.SHORTS,
    BracketType.ALLOCATORS,
)

SMALL_PERSONAS = [
    _persona("quants_01", BracketType.QUANTS),
    _persona("quants_02", BracketType.QUANTS),
    _persona("degens_01", BracketType.DEGENS),
    _persona("degens_02", BracketType.DEGENS),
    _persona("macro_01", BracketType.MACRO),
]

_PEER_LINE = re.compile(r"^\d+\. \[([a-z]+(?:_[a-z]+)*_\d{2})\|", re.MULTILINE)


def _decisions(
    personas: Sequence[AgentPersona],
    *,
    rationale: str = "Bullish on the setup.",
    cited: Sequence[str] = (),
) -> list[tuple[str, AgentDecision]]:
    return [
        (
            p.id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.7,
                rationale=rationale,
                cited_agents=[c for c in cited if c != p.id],
            ),
        )
        for p in personas
    ]


def _build(
    personas: Sequence[AgentPersona],
    decisions: Sequence[tuple[str, AgentDecision]],
    source_round: int,
    **kwargs: Any,
) -> tuple[list[str | None], list[tuple[str, ...]]]:
    kwargs.setdefault("sim", SimulationSettings())
    return _build_diverse_peer_contexts(list(personas), list(decisions), source_round, **kwargs)


class TestComputeExposureMetrics:
    def test_counts_slots_readers_and_distinct_peers(self) -> None:
        exposures = [
            ("degens_01", "degens_02", "macro_01"),  # reader quants_01
            ("degens_01", "quants_01"),  # reader quants_02
            ("quants_01",),  # reader degens_01
            (),  # reader degens_02 saw nobody
            ("quants_01", "quants_02"),  # reader macro_01
        ]

        metrics = compute_exposure_metrics(exposures, SMALL_PERSONAS, round_num=2)

        assert metrics == {
            "r2_exposure_quants": 4,
            "r2_readers_seeing_quants": 3,
            "r2_exposure_degens": 3,
            "r2_readers_seeing_degens": 2,
            "r2_exposure_macro": 1,
            "r2_readers_seeing_macro": 1,
            "r2_distinct_peers_shown": 5,
        }

    def test_unseen_brackets_report_zero(self) -> None:
        no_peers = [()] * len(SMALL_PERSONAS)

        metrics = compute_exposure_metrics(no_peers, SMALL_PERSONAS, round_num=3)

        assert metrics["r3_exposure_macro"] == 0
        assert metrics["r3_readers_seeing_macro"] == 0
        assert metrics["r3_distinct_peers_shown"] == 0
        assert len(metrics) == 7  # 3 brackets x 2 keys + distinct

    def test_ignores_ids_outside_the_roster(self) -> None:
        metrics = compute_exposure_metrics([("ghost_99", "quants_01")], SMALL_PERSONAS, round_num=2)

        assert metrics["r2_exposure_quants"] == 1
        assert metrics["r2_distinct_peers_shown"] == 1
        assert not any("ghost" in key for key in metrics)

    def test_keys_follow_roster_bracket_order(self) -> None:
        personas = generate_personas(DEFAULT_BRACKETS)

        metrics = compute_exposure_metrics([()] * len(personas), personas, round_num=2)

        exposure_keys = [key for key in metrics if key.startswith("r2_exposure_")]
        assert exposure_keys == [f"r2_exposure_{b.bracket_type.value}" for b in DEFAULT_BRACKETS]


class TestBuildDiversePeerContexts:
    def test_exposures_align_with_personas_and_rendered_lines(self) -> None:
        contexts, exposures = _build(SMALL_PERSONAS, _decisions(SMALL_PERSONAS), 1)

        assert len(contexts) == len(exposures) == len(SMALL_PERSONAS)
        for persona, ctx, shown in zip(SMALL_PERSONAS, contexts, exposures, strict=True):
            assert ctx is not None
            assert list(shown) == _PEER_LINE.findall(ctx)
            assert persona.id not in shown
            assert len(shown) == len(SMALL_PERSONAS) - 1

    def test_exposures_match_rendered_lines_when_budget_truncates(self) -> None:
        """Peers cut by the character budget are not exposure."""
        long_take = "word " * 400  # 2,000 characters per rationale

        contexts, exposures = _build(
            SMALL_PERSONAS, _decisions(SMALL_PERSONAS, rationale=long_take), 1
        )

        for ctx, shown in zip(contexts, exposures, strict=True):
            assert ctx is not None
            assert 1 <= len(shown) < len(SMALL_PERSONAS) - 1
            assert list(shown) == _PEER_LINE.findall(ctx)

    def test_reader_without_eligible_peers_gets_none_and_empty_exposure(self) -> None:
        """When every other agent failed last round, the reader sees nobody."""
        survivor = SMALL_PERSONAS[0]
        decisions = [
            (
                p.id,
                AgentDecision(
                    signal=SignalType.BUY if p is survivor else SignalType.PARSE_ERROR,
                    confidence=0.5,
                    rationale="ok",
                ),
            )
            for p in SMALL_PERSONAS
        ]

        contexts, exposures = _build(SMALL_PERSONAS, decisions, 1)

        assert contexts[0] is None
        assert exposures[0] == ()
        for ctx, shown in zip(contexts[1:], exposures[1:], strict=True):
            assert ctx is not None
            assert shown == (survivor.id,)

    def test_peer_limit_sets_selection_and_rendered_line_count(self) -> None:
        personas = [_persona(f"{b.value}_{i:02d}", b) for b in FIVE_BRACKETS for i in range(1, 4)]

        _, exposures = _build(
            personas, _decisions(personas), 1, sim=SimulationSettings(peer_limit=12)
        )

        assert {len(shown) for shown in exposures} == {12}

    def test_personal_boost_and_limits_come_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        def fake_select(
            agent_id: str,
            influence_weights: dict[str, float],
            personas: list[AgentPersona],
            prev_decisions: dict[str, AgentDecision] | None = None,
            **kwargs: Any,
        ) -> list[str]:
            captured.append({"agent_id": agent_id, "weights": dict(influence_weights), **kwargs})
            return []

        monkeypatch.setattr("alphaswarm.simulation.select_diverse_peers", fake_select)
        sim = SimulationSettings(personal_boost=0.05, peer_limit=7, min_brackets=2, bracket_cap=2)

        contexts, exposures = _build(
            SMALL_PERSONAS, _decisions(SMALL_PERSONAS, cited=("degens_01",)), 2, sim=sim
        )

        first = captured[0]  # reader quants_01 cited degens_01 last round
        assert first["agent_id"] == "quants_01"
        assert first["weights"]["degens_01"] == pytest.approx(0.5 + 0.05)
        assert first["weights"]["degens_02"] == pytest.approx(0.5)
        assert first["limit"] == 7
        assert first["min_brackets"] == 2
        assert contexts == [None] * len(SMALL_PERSONAS)
        assert exposures == [()] * len(SMALL_PERSONAS)


def _provider(role: ProviderRole, model: str, *, local: bool) -> FakeInferenceProvider:
    return FakeInferenceProvider(role, model, scripted=[], is_local=local)


ORCH = ProviderRole.ORCHESTRATOR
WORKER = ProviderRole.WORKER


class TestPeerAndProvenanceMetrics:
    @pytest.mark.parametrize(
        ("orch_local", "worker_local", "orch_label", "worker_label", "mode"),
        [
            (True, True, "ollama", "ollama", "local"),
            (True, False, "ollama", "cloud", "mixed"),
            (False, True, "cloud", "ollama", "mixed"),
            (False, False, "cloud", "cloud", "cloud"),
        ],
    )
    def test_provider_labels_models_and_mode(
        self,
        orch_local: bool,
        worker_local: bool,
        orch_label: str,
        worker_label: str,
        mode: str,
    ) -> None:
        """Cloud and mixed runs are labelled from the protocol alone."""
        orch = _provider(ORCH, "orch-model", local=orch_local)
        worker = _provider(WORKER, "worker-model", local=worker_local)

        metrics = _peer_and_provenance_metrics(
            SimulationSettings(), orch, worker, git_sha="a" * 40, git_dirty=False
        )

        assert metrics["orchestrator_provider"] == orch_label
        assert metrics["worker_provider"] == worker_label
        assert metrics["orchestrator_model"] == "orch-model"
        assert metrics["worker_model"] == "worker-model"
        assert metrics["inference_mode"] == mode
        assert metrics["git_sha"] == "a" * 40
        assert metrics["git_dirty"] is False

    def test_peer_params_reflect_settings(self) -> None:
        sim = SimulationSettings(
            peer_limit=12,
            min_brackets=5,
            bracket_cap=2,
            personal_boost=0.05,
            peer_budget_chars=6000,
        )

        metrics = _peer_and_provenance_metrics(
            sim,
            _provider(ORCH, "o", local=True),
            _provider(WORKER, "w", local=True),
            git_sha=None,
            git_dirty=None,
        )

        assert metrics["peer_selection_version"] == 1
        assert metrics["peer_limit"] == 12
        assert metrics["peer_min_brackets"] == 5
        assert metrics["peer_budget_chars"] == 6000
        assert metrics["peer_personal_boost"] == 0.05

    def test_unknown_git_state_is_empty_sha_and_no_dirty_key(self) -> None:
        metrics = _peer_and_provenance_metrics(
            SimulationSettings(),
            _provider(ORCH, "o", local=True),
            _provider(WORKER, "w", local=True),
            git_sha=None,
            git_dirty=None,
        )

        assert metrics["git_sha"] == ""
        assert "git_dirty" not in metrics

    def test_values_are_flat_scalars(self) -> None:
        metrics = _peer_and_provenance_metrics(
            SimulationSettings(),
            _provider(ORCH, "o", local=False),
            _provider(WORKER, "w", local=True),
            git_sha="c" * 40,
            git_dirty=True,
        )

        assert all(isinstance(v, (int, float, str, bool)) for v in metrics.values())
