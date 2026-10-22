"""Peer selection, exposure and provenance (docs/DECISIONS.md#adr-diverse-peer-context)."""

from __future__ import annotations

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas
from alphaswarm.simulation import compute_exposure_metrics
from alphaswarm.types import AgentPersona, BracketType


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
