"""Portable cycle export: one cycle as a self-contained JSON document.

Format ``alphaswarm.cycle-export/1`` (docs/DECISIONS.md#adr-cycle-export): the
cycle metadata and flat metric map, the run manifest when one was stored, the
roster in config order, every round's decisions and citations, the shocks and
the report markdown. It never holds the peer prompt text or portfolio data; the
import-linter contract "Export isolation" keeps this module away from
``alphaswarm.holdings`` and ``alphaswarm.advisory``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphaswarm.errors import CycleNotFoundError, CycleNotReadyError
from alphaswarm.manifest import RunManifest
from alphaswarm.personas import BRACKET_DISPLAY_NAMES, bracket_sort_key

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.graph.rows import (
        CycleCitationRow,
        CycleExportRows,
        ExportCycleRow,
        ExportDecisionRow,
    )

log = structlog.get_logger(component="export")

EXPORT_SCHEMA: Final = "alphaswarm.cycle-export/1"


class ExportAgent(BaseModel):
    """One roster entry; display_name falls back to the bracket for older compositions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    bracket: str
    display_name: str
    influence_weight_base: float
    temperature: float


class ExportDecision(BaseModel):
    """One agent's decision in one round. peer_ids keep the order shown in the prompt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    signal: str
    confidence: float
    sentiment: float
    rationale: str
    cited_agent_ids: list[str]
    peer_ids: list[str]
    control: bool


class ExportCitation(BaseModel):
    """source_id cited target_id; cited_signal is target_id's previous-round signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    target_id: str
    cited_signal: str


class ExportRound(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    round_num: int
    decisions: list[ExportDecision]
    citations: list[ExportCitation]


class ExportShock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    injected_before_round: int


class ExportCycleMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    created_at: datetime
    seed_rumor: str
    overall_sentiment: float | None
    num_rounds: int
    status: str
    metrics: dict[str, float | int | str | bool]
    manifest: RunManifest | None


class CycleExport(BaseModel):
    """A whole cycle, versioned by ``schema`` (docs/DECISIONS.md#adr-cycle-export)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["alphaswarm.cycle-export/1"] = Field(default="alphaswarm.cycle-export/1", alias="schema")
    cycle: ExportCycleMeta
    roster: list[ExportAgent]
    rounds: list[ExportRound]
    report_markdown: str | None
    shocks: list[ExportShock]


def _decision(row: ExportDecisionRow) -> ExportDecision:
    return ExportDecision(
        agent_id=row["agent_id"],
        signal=row["signal"],
        confidence=row["confidence"],
        sentiment=row["sentiment"],
        rationale=row["rationale"],
        cited_agent_ids=sorted(set(row["cited_agent_ids"])),
        peer_ids=list(row["peer_ids"]),
        control=row["control"],
    )


def _manifest(cycle: ExportCycleRow) -> RunManifest | None:
    raw = cycle["run_manifest_json"]
    if raw is None:
        return None
    try:
        return RunManifest.model_validate_json(raw)
    except ValidationError as exc:
        log.warning("export_manifest_unreadable", cycle_id=cycle["cycle_id"], errors=exc.error_count())
        return None


def build_export(rows: CycleExportRows, *, status: str, report_markdown: str | None) -> CycleExport:
    """Assemble a CycleExport from graph rows (pure).

    The roster follows config order and agents of older compositions sort after
    it; decisions follow the roster; cited ids are de-duplicated and sorted.
    num_rounds falls back to the last round present when the cycle never stored it.
    """
    cycle = rows["cycle"]
    if cycle is None:
        raise ValueError("export rows hold no cycle")
    agents = sorted(rows["agents"], key=lambda a: (bracket_sort_key(a["bracket"]), a["agent_id"]))
    position = {a["agent_id"]: index for index, a in enumerate(agents)}
    decisions_by_round: dict[int, list[ExportDecisionRow]] = defaultdict(list)
    for decision in rows["decisions"]:
        decisions_by_round[decision["round_num"]].append(decision)
    citations_by_round: dict[int, list[CycleCitationRow]] = defaultdict(list)
    for citation in rows["citations"]:
        citations_by_round[citation["round_num"]].append(citation)

    def roster_order(row: ExportDecisionRow) -> tuple[int, str]:
        return (position.get(row["agent_id"], len(position)), row["agent_id"])

    rounds = [
        ExportRound(
            round_num=round_num,
            decisions=[_decision(d) for d in sorted(decisions_by_round[round_num], key=roster_order)],
            citations=[
                ExportCitation(source_id=c["source_id"], target_id=c["target_id"], cited_signal=c["cited_signal"])
                for c in citations_by_round.get(round_num, [])
            ],
        )
        for round_num in sorted(decisions_by_round)
    ]
    num_rounds = cycle["num_rounds"] if cycle["num_rounds"] is not None else max(decisions_by_round, default=0)
    return CycleExport(
        cycle=ExportCycleMeta(
            cycle_id=cycle["cycle_id"],
            created_at=datetime.fromisoformat(cycle["created_at"]),
            seed_rumor=cycle["seed_rumor"],
            overall_sentiment=cycle["overall_sentiment"],
            num_rounds=num_rounds,
            status=status,
            metrics=dict(cycle["metrics"]),
            manifest=_manifest(cycle),
        ),
        roster=[
            ExportAgent(
                id=a["agent_id"],
                name=a["name"],
                bracket=a["bracket"],
                display_name=BRACKET_DISPLAY_NAMES.get(a["bracket"], a["bracket"]),
                influence_weight_base=a["influence_weight_base"],
                temperature=a["temperature"],
            )
            for a in agents
        ],
        rounds=rounds,
        report_markdown=report_markdown,
        shocks=[ExportShock(text=s["text"], injected_before_round=s["injected_before_round"]) for s in rows["shocks"]],
    )


async def _read_report(reports_dir: Path, cycle_id: str) -> str | None:
    path = reports_dir / f"{cycle_id}_report.md"

    def read() -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    return await asyncio.to_thread(read)


async def export_cycle(gm: GraphStateManager, cycle_id: str, *, reports_dir: Path) -> CycleExport:
    """Export one finished cycle (complete, failed or cancelled).

    Raises CycleNotFoundError for an unknown id and CycleNotReadyError while the
    cycle is still running (its rows would be a moving target).
    """
    status = await gm.read_cycle_status(cycle_id)
    if status is None:
        raise CycleNotFoundError(cycle_id)
    if status == "running":
        raise CycleNotReadyError(cycle_id, status)
    rows = await gm.read_cycle_export_rows(cycle_id)
    if rows["cycle"] is None:  # deleted between the two reads
        raise CycleNotFoundError(cycle_id)
    report_markdown = await _read_report(reports_dir, cycle_id)
    export = build_export(rows, status=status, report_markdown=report_markdown)
    log.info(
        "cycle_exported",
        cycle_id=cycle_id,
        status=status,
        rounds=len(export.rounds),
        decisions=sum(len(r.decisions) for r in export.rounds),
        has_report=report_markdown is not None,
    )
    return export


def export_json(export: CycleExport) -> str:
    """Compact UTF-8 JSON with the ``schema`` key (what the CLI and the demo store)."""
    return export.model_dump_json(by_alias=True)
