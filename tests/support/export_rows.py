"""A small fictional CycleExportRows value for export, route and CLI tests.

Three agents: two from today's roster and one archival agent from an older
composition (bracket "whales"), two rounds, one citation and one shock.
"""

from __future__ import annotations

from typing import Final

from alphaswarm.graph.rows import (
    CycleCitationRow,
    CycleExportRows,
    ExportAgentRow,
    ExportCycleRow,
    ExportDecisionRow,
    ExportShockRow,
)

EXPORT_CYCLE_ID: Final = "00000000-0000-4000-8000-0000000000a1"
EXPORT_RUMOR: Final = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
EXPORT_SHOCK: Final = "QQQX Robotics says the ZZZT talks ended without a deal."


def _decision(
    round_num: int,
    agent_id: str,
    signal: str,
    confidence: float,
    *,
    cited: tuple[str, ...] = (),
    peers: tuple[str, ...] = (),
    control: bool = False,
) -> ExportDecisionRow:
    return ExportDecisionRow(
        round_num=round_num,
        agent_id=agent_id,
        signal=signal,
        confidence=confidence,
        sentiment=0.2 if signal == "buy" else -0.2 if signal == "sell" else 0.0,
        rationale=f"{agent_id} round {round_num}: {signal.upper()} — the ZZZT premium looks thin.",
        cited_agent_ids=list(cited),
        peer_ids=list(peers),
        control=control,
    )


def make_export_rows(
    *,
    cycle_id: str = EXPORT_CYCLE_ID,
    num_rounds: int | None = 2,
    run_manifest_json: str | None = None,
) -> CycleExportRows:
    return CycleExportRows(
        cycle=ExportCycleRow(
            cycle_id=cycle_id,
            created_at="2026-10-03T12:00:00.123456+00:00",
            seed_rumor=EXPORT_RUMOR,
            overall_sentiment=0.3,
            num_rounds=num_rounds,
            run_manifest_json=run_manifest_json,
            metrics={
                "metrics_version": 3,
                "final_buy": 0,
                "final_sell": 2,
                "final_hold": 1,
                "r2_flips": 1,
                "git_dirty": False,
                "worker_model": "alphaswarm-worker",
            },
        ),
        agents=[
            ExportAgentRow(
                agent_id="legacy_whale_01", name="Whale 1", bracket="whales", influence_weight_base=0.5, temperature=0.7
            ),
            ExportAgentRow(
                agent_id="quants_01", name="Quants 1", bracket="quants", influence_weight_base=0.6, temperature=0.3
            ),
            ExportAgentRow(
                agent_id="sell_side_01",
                name="Sell-Side 1",
                bracket="sell_side",
                influence_weight_base=0.9,
                temperature=0.4,
            ),
        ],
        decisions=[
            _decision(1, "legacy_whale_01", "hold", 0.5),
            _decision(1, "quants_01", "buy", 0.7),
            _decision(1, "sell_side_01", "sell", 0.8),
            _decision(2, "legacy_whale_01", "hold", 0.5),
            _decision(
                2,
                "quants_01",
                "sell",
                0.75,
                cited=("sell_side_01", "sell_side_01"),
                peers=("sell_side_01", "legacy_whale_01"),
            ),
            _decision(2, "sell_side_01", "sell", 0.85, control=True),
        ],
        citations=[CycleCitationRow(round_num=2, source_id="quants_01", target_id="sell_side_01", cited_signal="sell")],
        shocks=[ExportShockRow(text=EXPORT_SHOCK, injected_before_round=2)],
    )
