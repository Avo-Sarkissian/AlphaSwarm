"""Peer selection, exposure and provenance (docs/DECISIONS.md#adr-diverse-peer-context)."""

from __future__ import annotations

import dataclasses
import hashlib
import math
import random
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from alphaswarm.config import DEFAULT_BRACKETS, SimulationSettings, generate_personas
from alphaswarm.inference.types import ProviderRole
from alphaswarm.simulation import (
    _build_diverse_peer_contexts,
    _peer_and_provenance_metrics,
    compute_exposure_metrics,
    peer_rng,
    select_diverse_peers,
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

RUN_SEED = "00000000-0000-4000-8000-000000000001"
INVARIANT_RUN_SEEDS = (
    "00000000-0000-4000-8000-000000000001",
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
)

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
    kwargs.setdefault("run_seed", RUN_SEED)
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

    def test_peer_budget_chars_comes_from_settings(self) -> None:
        """The budget in settings, not the formatter's default, decides what renders."""
        decisions = _decisions(SMALL_PERSONAS, rationale="word " * 60)  # 300-char takes

        _, roomy = _build(SMALL_PERSONAS, decisions, 1)
        _, tight = _build(
            SMALL_PERSONAS, decisions, 1, sim=SimulationSettings(peer_budget_chars=500)
        )

        assert {len(shown) for shown in roomy} == {len(SMALL_PERSONAS) - 1}
        assert {len(shown) for shown in tight} == {1}

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
        assert first["bracket_cap"] == 2
        assert isinstance(first["rng"], random.Random)
        assert first["rng"].random() == peer_rng(RUN_SEED, "quants_01", 3).random()
        assert contexts == [None] * len(SMALL_PERSONAS)
        assert exposures == [()] * len(SMALL_PERSONAS)

    def test_same_run_seed_reproduces_contexts(self) -> None:
        personas = generate_personas(DEFAULT_BRACKETS)
        decisions = _decisions(personas)

        first = _build(personas, decisions, 1)

        assert _build(personas, decisions, 1) == first
        assert _build(personas, decisions, 1, run_seed="other-seed")[1] != first[1]


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

        assert metrics["peer_selection_version"] == 2
        assert metrics["peer_limit"] == 12
        assert metrics["peer_min_brackets"] == 5
        assert metrics["peer_bracket_cap"] == 2
        assert metrics["peer_seed_source"] == "cycle_id"
        assert metrics["peer_budget_chars"] == 6000
        assert metrics["peer_personal_boost"] == 0.05

    @pytest.mark.parametrize(("own_prior_memory", "control_fraction"), [(True, 0.0), (False, 0.2)])
    def test_experiment_knobs_reflect_settings(
        self, own_prior_memory: bool, control_fraction: float
    ) -> None:
        """A cycle run without the own prior or with a holdout must not look like a default one."""
        sim = SimulationSettings(
            own_prior_memory=own_prior_memory, control_fraction=control_fraction
        )

        metrics = _peer_and_provenance_metrics(
            sim,
            _provider(ORCH, "o", local=True),
            _provider(WORKER, "w", local=True),
            git_sha=None,
            git_dirty=None,
        )

        assert metrics["own_prior_memory"] is own_prior_memory
        assert metrics["control_fraction"] == control_fraction

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


class TestPeerRng:
    def test_matches_pinned_value(self) -> None:
        """Pinned so a refactor cannot silently change every run's peer draws."""
        rng = peer_rng("00000000-0000-4000-8000-000000000001", "sell_side_01", 2)

        assert rng.random() == 0.11489473118130222

    def test_seed_is_blake2b_of_run_reader_round(self) -> None:
        digest = hashlib.blake2b(b"run:quants_01:3", digest_size=8).digest()
        expected = random.Random(int.from_bytes(digest, "big"))

        assert peer_rng("run", "quants_01", 3).random() == expected.random()

    def test_differs_by_reader_round_and_run(self) -> None:
        base = peer_rng("run", "quants_01", 2).random()

        assert peer_rng("run", "quants_02", 2).random() != base
        assert peer_rng("run", "quants_01", 3).random() != base
        assert peer_rng("other", "quants_01", 2).random() != base


def _bracket(agent_id: str) -> str:
    return agent_id.rsplit("_", 1)[0]


def _select(
    agent_id: str,
    weights: dict[str, float],
    personas: Sequence[AgentPersona],
    prev: dict[str, AgentDecision] | None = None,
    *,
    seed: int = 0,
    **kwargs: Any,
) -> list[str]:
    return select_diverse_peers(
        agent_id, weights, personas, prev, rng=random.Random(seed), **kwargs
    )


class _ScriptedRandom(random.Random):
    """``random()`` returns ``values`` in order, then continues a seeded stream."""

    def __init__(self, values: Sequence[float]) -> None:
        super().__init__(0)
        self._values = list(values)

    def random(self) -> float:
        return self._values.pop(0) if self._values else super().random()


_LUCKIEST_DRAW = 1.0 - 2.0**-53  # the largest value random() can return


class TestSelectDiversePeers:
    def test_requires_an_explicit_rng(self) -> None:
        with pytest.raises(TypeError, match="rng"):
            select_diverse_peers("quants_01", {}, SMALL_PERSONAS)  # type: ignore[call-arg]

    def test_phase1_guarantees_min_brackets(self) -> None:
        personas = [_persona(f"{b.value}_{i:02d}", b) for b in FIVE_BRACKETS for i in range(1, 7)]
        weights = {p.id: (2.0 if p.bracket is BracketType.QUANTS else 0.1) for p in personas}

        for seed in range(50):
            out = _select("degens_01", weights, personas, seed=seed, limit=5, min_brackets=4)
            assert len(out) == 5
            assert len({_bracket(pid) for pid in out}) >= 4

    def test_cap_binds_when_few_brackets_remain(self) -> None:
        """Two eligible brackets x cap 3 gives 6 peers, not 10."""
        personas = [_persona(f"quants_{i:02d}", BracketType.QUANTS) for i in range(1, 8)] + [
            _persona(f"degens_{i:02d}", BracketType.DEGENS) for i in range(1, 8)
        ]

        out = _select("quants_01", {p.id: 0.5 for p in personas}, personas, seed=3)

        assert len(out) == 6
        assert Counter(_bracket(pid) for pid in out) == {"quants": 3, "degens": 3}

    def test_all_peers_parse_error_yields_no_peers(self) -> None:
        """Nobody eligible means an empty list, not an error."""
        prev = {
            p.id: AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)
            for p in SMALL_PERSONAS
            if p.id != "quants_01"
        }

        assert _select("quants_01", {p.id: 0.5 for p in SMALL_PERSONAS}, SMALL_PERSONAS, prev) == []

    def test_degenerate_weights_never_raise(self) -> None:
        """NaN, inf, negative, zero and missing weights do not crash a round."""
        personas = [_persona(f"quants_{i:02d}", BracketType.QUANTS) for i in range(1, 5)] + [
            _persona(f"degens_{i:02d}", BracketType.DEGENS) for i in range(1, 5)
        ]
        weights = {
            "quants_01": math.nan,
            "quants_02": math.inf,
            "quants_03": -1.0,
            "quants_04": 0.0,
            "degens_01": 0.5,
        }

        out = _select("degens_02", weights, personas, seed=7, min_brackets=2)

        assert len(out) == 6

    def test_positive_weight_beats_degenerate_weights(self) -> None:
        """Invalid weights only push a candidate to the back."""
        personas = [_persona(f"quants_{i:02d}", BracketType.QUANTS) for i in range(1, 5)] + [
            _persona(f"degens_{i:02d}", BracketType.DEGENS) for i in range(1, 5)
        ]
        weights = {
            "quants_01": math.nan,
            "quants_02": math.inf,
            "quants_03": -1.0,
            "quants_04": 0.0,
            "degens_01": 0.5,
        }

        for seed in range(50):
            out = _select("degens_02", weights, personas, seed=seed, limit=1, min_brackets=0)
            assert out == ["degens_01"]

    @pytest.mark.parametrize(
        ("draws", "min_brackets"),
        [
            # Candidate keys draw first, in roster order: quants_01, then degens_01.
            ((_LUCKIEST_DRAW, 0.5), 0),
            # Then the bracket keys: quants, then degens.
            ((0.5, 0.5, _LUCKIEST_DRAW, 0.5), 1),
        ],
        ids=["fill", "guaranteed-bracket"],
    )
    def test_degenerate_weight_loses_even_its_luckiest_draw(
        self, draws: tuple[float, ...], min_brackets: int
    ) -> None:
        """No draw lifts a weight without reach over a positive one, in either phase."""
        personas = [
            _persona("quants_01", BracketType.QUANTS),
            _persona("degens_01", BracketType.DEGENS),
        ]
        weights = {"quants_01": math.nan, "degens_01": 0.5}

        out = select_diverse_peers(
            "macro_01",
            weights,
            personas,
            rng=_ScriptedRandom(draws),
            limit=1,
            min_brackets=min_brackets,
        )

        assert out == ["degens_01"]

    def test_min_brackets_larger_than_limit(self) -> None:
        """An odd but legal setting degrades to one peer per bracket."""
        out = _select(
            "macro_01",
            {p.id: 0.5 for p in SMALL_PERSONAS},
            SMALL_PERSONAS,
            limit=2,
            min_brackets=10,
        )

        assert len(out) == 2
        assert len({_bracket(pid) for pid in out}) == 2

    def test_invalid_bracket_cap_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="bracket_cap"):
            _select("quants_01", {}, SMALL_PERSONAS, bracket_cap=0)

    def test_same_rng_seed_reproduces_selection(self) -> None:
        personas = generate_personas(DEFAULT_BRACKETS)
        weights = {p.id: p.influence_weight_base for p in personas}

        first = _select("quants_01", weights, personas, seed=42)

        assert _select("quants_01", weights, personas, seed=42) == first
        assert _select("quants_01", weights, personas, seed=43) != first

    def test_equal_weights_disperse_across_readers(self) -> None:
        """Successor of the F-08 tie-break test: equal weights still differ per reader."""
        personas = [
            _persona(f"{b.value}_{j:02d}", b)
            for b in (*FIVE_BRACKETS[:4], BracketType.NARRATORS)
            for j in range(1, 21)
        ]
        weights = {p.id: 0.5 for p in personas}

        peer_sets = {
            tuple(
                select_diverse_peers(
                    p.id, weights, personas, rng=peer_rng(RUN_SEED, p.id, 2), limit=5
                )
            )
            for p in personas
        }

        assert len(peer_sets) >= 50

    def test_higher_weight_is_seen_more_often_but_not_always(self) -> None:
        """Reach is a probability: the R3 boost raises a cited author's odds, never guarantees."""
        personas = generate_personas(DEFAULT_BRACKETS)
        base = {p.id: p.influence_weight_base for p in personas}
        boosted = {**base, "degens_01": base["degens_01"] + 0.3}

        def hits(weights: dict[str, float]) -> int:
            return sum(
                "degens_01"
                in select_diverse_peers(
                    "quants_01", weights, personas, rng=peer_rng(f"seed-{i}", "quants_01", 3)
                )
                for i in range(400)
            )

        assert hits(base) < hits(boosted) < 400

    def test_guaranteed_bracket_odds_follow_summed_reach(self) -> None:
        """One guaranteed slot is a weighted draw over agents, whatever the bracket size.

        Nine quants and one degen of equal weight give the lone degen about 1 in
        10. Weighting a bracket by its best member alone gives it about 1 in 2.
        """
        personas = [_persona(f"quants_{i:02d}", BracketType.QUANTS) for i in range(1, 10)] + [
            _persona("degens_01", BracketType.DEGENS)
        ]
        weights = {p.id: 0.5 for p in personas}

        hits = sum(
            _select("macro_01", weights, personas, seed=seed, limit=1, min_brackets=1)
            == ["degens_01"]
            for seed in range(1000)
        )

        assert 50 <= hits <= 150

    def test_highest_reach_brackets_are_seen_most_per_agent(self) -> None:
        """Per agent, the two highest-weight brackets lead visibility on the production roster.

        Per-agent visibility is a bracket's slots divided by its size. The bracket
        floor and the per-bracket cap flatten the order below the top two, so
        only the top two are pinned (docs/DECISIONS.md#adr-diverse-peer-context).
        """
        personas = generate_personas(DEFAULT_BRACKETS)
        weights = {p.id: p.influence_weight_base for p in personas}
        size = Counter(p.bracket.value for p in personas)
        reach = {p.bracket.value: p.influence_weight_base for p in personas}
        top_two = sorted(size, key=lambda b: reach[b], reverse=True)[:2]
        slots: Counter[str] = Counter()
        for i in range(100):
            for p in personas:
                rng = peer_rng(f"reach-{i}", p.id, 2)
                peers = select_diverse_peers(p.id, weights, personas, rng=rng)
                slots.update(_bracket(pid) for pid in peers)

        per_agent = {b: slots[b] / size[b] for b in size}
        assert set(top_two) == {"sell_side", "narrators"}
        others = max(per_agent[b] for b in size if b not in top_two)
        assert min(per_agent[b] for b in top_two) > others, per_agent


_ALL_BRACKETS = tuple(BracketType)


@dataclasses.dataclass(frozen=True)
class _SelectionCase:
    personas: tuple[AgentPersona, ...]
    reader: str
    weights: dict[str, float]
    prev: dict[str, AgentDecision]
    limit: int
    min_brackets: int
    bracket_cap: int
    seed: int


@st.composite
def _selection_cases(draw: st.DrawFn) -> _SelectionCase:
    counts = draw(
        st.lists(st.integers(0, 6), min_size=len(_ALL_BRACKETS), max_size=len(_ALL_BRACKETS))
    )
    personas = tuple(
        _persona(f"{bracket.value}_{i:02d}", bracket)
        for bracket, count in zip(_ALL_BRACKETS, counts, strict=True)
        for i in range(1, count + 1)
    )
    assume(personas)
    ids = [p.id for p in personas]
    weights = {pid: draw(st.floats(min_value=0.0, max_value=2.0, allow_nan=False)) for pid in ids}
    failed = draw(st.sets(st.sampled_from(ids)))
    return _SelectionCase(
        personas=personas,
        reader=draw(st.sampled_from(ids)),
        weights=weights,
        prev={pid: AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0) for pid in failed},
        limit=draw(st.integers(1, 20)),
        min_brackets=draw(st.integers(0, 10)),
        bracket_cap=draw(st.integers(1, 10)),
        seed=draw(st.integers(0, 2**32 - 1)),
    )


@settings(max_examples=200, deadline=None)
@given(case=_selection_cases())
def test_selection_properties(case: _SelectionCase) -> None:
    """Self and PARSE_ERROR exclusion, slot limit, cap, maximal fill, diversity, determinism."""

    def run() -> list[str]:
        return select_diverse_peers(
            case.reader,
            case.weights,
            case.personas,
            case.prev,
            rng=random.Random(case.seed),
            limit=case.limit,
            min_brackets=case.min_brackets,
            bracket_cap=case.bracket_cap,
        )

    out = run()
    bracket_of = {p.id: p.bracket.value for p in case.personas}
    per_bracket = Counter(bracket_of[pid] for pid in out)
    eligible = Counter(
        p.bracket.value for p in case.personas if p.id != case.reader and p.id not in case.prev
    )

    assert case.reader not in out
    assert not set(out) & set(case.prev)
    assert len(out) == len(set(out))
    assert len(out) <= case.limit
    assert all(n <= case.bracket_cap for n in per_bracket.values())
    assert len(out) == min(case.limit, sum(min(case.bracket_cap, n) for n in eligible.values()))
    assert len(per_bracket) >= min(case.min_brackets, case.limit, len(eligible))
    assert out == run()


class TestExposureInvariant:
    """No bracket dominates and every bracket is heard, on the production roster.

    See docs/DECISIONS.md#adr-diverse-peer-context.
    """

    MAX_SLOT_SHARE = 0.35
    MIN_READER_SHARE = 0.15

    def _check(
        self, exposures: list[tuple[str, ...]], personas: list[AgentPersona], round_num: int
    ) -> tuple[dict[str, int], int]:
        metrics = compute_exposure_metrics(exposures, personas, round_num)
        total = sum(metrics[f"r{round_num}_exposure_{b.value}"] for b in BracketType)
        assert total > 0
        for bracket in BracketType:
            slots = metrics[f"r{round_num}_exposure_{bracket.value}"]
            readers = metrics[f"r{round_num}_readers_seeing_{bracket.value}"]
            assert slots / total <= self.MAX_SLOT_SHARE, (bracket.value, slots, total)
            assert readers / len(personas) >= self.MIN_READER_SHARE, (bracket.value, readers)
        return metrics, total

    @pytest.mark.parametrize("run_seed", INVARIANT_RUN_SEEDS)
    def test_round2_every_bracket_heard_none_dominates(self, run_seed: str) -> None:
        personas = generate_personas(DEFAULT_BRACKETS)

        _, exposures = _build(personas, _decisions(personas), 1, run_seed=run_seed)

        metrics, total = self._check(exposures, personas, 2)
        assert total == len(personas) * SimulationSettings().peer_limit
        assert metrics["r2_distinct_peers_shown"] >= 90

    @pytest.mark.parametrize("run_seed", INVARIANT_RUN_SEEDS)
    def test_round3_herd_citations_stay_capped(self, run_seed: str) -> None:
        """Worst case for R3: everyone cited the same two Sell-Side agents."""
        personas = generate_personas(DEFAULT_BRACKETS)
        herd = ("sell_side_01", "sell_side_02")

        _, exposures = _build(
            personas,
            _decisions(personas, cited=herd),
            2,
            run_seed=run_seed,
            global_citation_weights={agent_id: 1.0 for agent_id in herd},
        )

        self._check(exposures, personas, 3)
        cap = SimulationSettings().bracket_cap
        for shown in exposures:
            assert sum(1 for pid in shown if pid.startswith("sell_side_")) <= cap

    def test_first_display_slot_carries_no_authority(self) -> None:
        """The legacy selector put Sell-Side at position 1 for every reader."""
        personas = generate_personas(DEFAULT_BRACKETS)

        _, exposures = _build(personas, _decisions(personas), 1)

        bracket_of = {p.id: p.bracket.value for p in personas}
        first = Counter(bracket_of[shown[0]] for shown in exposures)
        assert first["sell_side"] / len(personas) <= self.MAX_SLOT_SHARE
        assert len(first) >= 8
