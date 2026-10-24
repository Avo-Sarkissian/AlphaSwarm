"""compare_cycles --methodology renders the final round's estimators (docs/DECISIONS.md#adr-consensus-estimators)."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from tests.support.scripts import load_script

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_cycles.py"


def _load() -> ModuleType:
    return load_script("compare_cycles")


def test_methodology_table_reads_the_final_round_and_tolerates_missing_keys() -> None:
    script = _load()
    rows = script.methodology_table(
        [
            {
                "cycle_id": "00000000-0000-4000-8000-0000000000a1",
                "final_round": 3,
                "r3_net_score_headcount": 0.42,
                "r3_net_score_ci_low": 0.3,
                "r3_net_score_ci_high": 0.51,
                "r3_net_score_reach": 0.4,
                "r3_net_score_bracket_equal": 0.2,
                "r3_entropy": 0.8,
                "r3_polarization": 0.1,
                "r3_conformity_rate": 0.66,
                "r3_mean_abs_conf_delta": 0.05,
                "r3_citation_gini": 0.35,
                "r3_citation_validity_rate": 0.97,
            },
            {"cycle_id": "00000000-0000-4000-8000-0000000000b2", "num_rounds": 2},
        ]
    )
    header, first, legacy = rows
    assert header[:2] == ["cycle", "round"]
    assert first[:5] == ["00000000", "3", "+0.420", "+0.300", "+0.510"]
    assert first[header.index("conform")] == "0.660"
    assert legacy[1] == "2" and set(legacy[2:]) == {"-"}


def test_cli_exposes_the_flag() -> None:
    assert "--methodology" in SCRIPT.read_text(encoding="utf-8")
