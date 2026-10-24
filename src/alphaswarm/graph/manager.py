"""GraphStateManager: the single entry point to the Neo4j graph
(docs/DECISIONS.md#adr-neo4j-schema).

The facade owns the driver, the session/transaction helpers and the error
mapping (docs/DECISIONS.md#p4-d-07). Every other public method delegates in one
line to an operation in schema_writes, analytics or replay_interview, which
receive `self._read` / `self._write` as a TxRunner and return graph/rows.py rows.
Writes are batched, one transaction per call (docs/DECISIONS.md#p4-d-08).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, TypeVar

import structlog
from neo4j import unit_of_work
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import DriverError, Neo4jError

from alphaswarm.errors import GraphError, Neo4jQueryError, Neo4jUnavailableError, Neo4jWriteError
from alphaswarm.graph import analytics, replay_interview, schema_writes
from alphaswarm.graph.rows import _COMPLETE_ONLY

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import AsyncDriver

    from alphaswarm.episodes import EntityMatch, EntityRef, EpisodeRecord
    from alphaswarm.errors import RunErrorCode
    from alphaswarm.graph.rows import (
        AgentDecisionRow,
        AgentInterviewRows,
        BracketNarrativeRow,
        BracketRoundRow,
        CompletedCycleRow,
        ConsensusSummaryRow,
        CycleStatus,
        EntityImpactRow,
        FinalDecisionRow,
        InfluenceEdgeRow,
        InfluenceLeaderRow,
        KeyDissenterRow,
        PersistRoundResult,
        RationaleRoundRow,
        RoundTimelineRow,
        ShockEventRow,
        ShockImpactRow,
        SignalFlipRow,
    )
    from alphaswarm.manifest import RunManifest
    from alphaswarm.state import AgentState
    from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SeedEvent

log = structlog.get_logger(component="graph")

T = TypeVar("T")

# neo4j 5.x raises a pool-acquisition timeout as a code-less ClientError (6.0: a DriverError).
_POOL_ACQUISITION_TIMEOUT_MARKER: Final = "failed to obtain a connection from the pool"


def _map_graph_error(exc: Exception, *, op: str, write: bool) -> GraphError:
    """Map a neo4j driver/server error onto the GraphError family.

    ServiceUnavailable and SessionExpired subclass DriverError, not Neo4jError; a wrong
    password is neo4j's AuthError (a ClientError); a pool-acquisition timeout is a
    code-less ClientError. All three mean the database is unreachable (docs/DECISIONS.md#p4-d-07).
    """
    unavailable = isinstance(exc, (DriverError, Neo4jAuthError)) or (
        isinstance(exc, Neo4jError) and exc.code is None and _POOL_ACQUISITION_TIMEOUT_MARKER in str(exc)
    )
    if unavailable:
        return Neo4jUnavailableError(f"Neo4j is unavailable ({op})", exc, op=op)
    if write:
        return Neo4jWriteError(f"Neo4j write failed ({op})", exc, op=op)
    return Neo4jQueryError(f"Neo4j query failed ({op})", exc, op=op)


class GraphStateManager:
    """Facade over the graph modules; one short-lived session per operation."""

    def __init__(
        self,
        driver: AsyncDriver,
        personas: list[AgentPersona],
        database: str = "neo4j",
        *,
        query_timeout_s: float | None = None,
    ) -> None:
        self._driver = driver
        self._personas = personas
        self._database = database
        self._query_timeout_s = query_timeout_s

    def _unit(self, fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Attach the server-side transaction timeout, when one is configured."""
        if self._query_timeout_s is None:
            return fn
        return unit_of_work(timeout=self._query_timeout_s)(fn)

    async def _read(self, fn: Callable[..., Awaitable[T]], *args: Any, op: str) -> T:
        """Run *fn* in a managed read transaction on a fresh session.

        The only place (with _write and ensure_schema's DDL) that opens a
        session; driver errors leave as GraphError (docs/DECISIONS.md#p4-d-07).
        """
        try:
            async with self._driver.session(database=self._database) as session:
                return await session.execute_read(self._unit(fn), *args)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op=op, write=False) from exc

    async def _write(self, fn: Callable[..., Awaitable[T]], *args: Any, op: str) -> T:
        """Run *fn* in a managed write transaction on a fresh session."""
        try:
            async with self._driver.session(database=self._database) as session:
                return await session.execute_write(self._unit(fn), *args)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op=op, write=True) from exc

    async def verify_connectivity(self) -> None:
        """Fail fast when the database is unreachable (docs/DECISIONS.md#p4-d-05).

        Raises only GraphError subclasses (Neo4jUnavailableError for driver and
        auth errors); the web lifespan turns them into a not-ready flag.
        """
        try:
            await self._driver.verify_connectivity()
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op="verify_connectivity", write=False) from exc

    async def close(self) -> None:
        await self._driver.close()
        log.info("driver_closed")

    async def ensure_schema(self) -> None:
        """Apply idempotent schema constraints and indexes, then seed agents.

        DDL runs as auto-commit statements on one session, the only one opened outside _read/_write
        (docs/DECISIONS.md#p4-d-05). It then back-fills ``Cycle.status`` and seeds all agent nodes. It removes
        no data: the retired Agent-level ``decision_narrative`` stays until ``remove_legacy_properties()`` runs,
        and duplicate decision ids keep the plain index in place of the uniqueness constraint; they are never deleted.
        """
        statements = await schema_writes.resolve_schema_statements(self._read)
        try:
            async with self._driver.session(database=self._database) as session:
                for stmt in statements:
                    await session.run(stmt)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op="ensure_schema", write=True) from exc
        log.info("schema_applied", statement_count=len(statements))
        await schema_writes.apply_data_maintenance(self._write)
        await self.seed_agents(self._personas)

    # --- schema and writes (graph/schema_writes.py) ---

    async def remove_legacy_properties(self) -> None:
        """Explicit, idempotent removal of retired properties; never run at startup."""
        await schema_writes.remove_legacy_properties(self._write)

    async def seed_agents(self, agents: list[AgentPersona]) -> None:
        await schema_writes.seed_agents(self._write, agents)

    async def create_cycle_with_seed_event(
        self,
        seed_rumor: str,
        seed_event: SeedEvent,
        *,
        num_rounds: int,
        modifiers: Mapping[BracketType, str] | None = None,
        prompt_template_hash: str | None = None,
    ) -> str:
        return await schema_writes.create_cycle_with_seed_event(
            self._write,
            seed_rumor,
            seed_event,
            num_rounds=num_rounds,
            modifiers=modifiers,
            prompt_template_hash=prompt_template_hash,
        )

    async def set_cycle_status(
        self, cycle_id: str, status: CycleStatus, *, error_code: RunErrorCode | None = None
    ) -> None:
        await schema_writes.set_cycle_status(self._write, cycle_id, status, error_code=error_code)

    async def write_cycle_metrics(self, cycle_id: str, metrics: dict[str, float | int | str | bool]) -> None:
        await schema_writes.write_cycle_metrics(self._write, cycle_id, metrics)

    async def write_run_manifest(self, cycle_id: str, manifest: RunManifest) -> None:
        await schema_writes.write_run_manifest(self._write, cycle_id, manifest)

    async def persist_round(
        self,
        cycle_id: str,
        round_num: int,
        decisions: Sequence[tuple[str, AgentDecision]],
        *,
        decision_ids: Sequence[str],
        episodes: Sequence[EpisodeRecord],
        entity_matches: Sequence[EntityMatch],
        control_ids: Collection[str] = (),
        exposures: Mapping[str, Sequence[str]] | None = None,
        citations_invalid: Mapping[str, int] | None = None,
        shock_treated_ids: Collection[str] | None = None,
    ) -> PersistRoundResult:
        return await schema_writes.persist_round(
            self._write,
            cycle_id,
            round_num,
            decisions,
            decision_ids=decision_ids,
            episodes=episodes,
            entity_matches=entity_matches,
            control_ids=control_ids,
            exposures=exposures,
            citations_invalid=citations_invalid,
            shock_treated_ids=shock_treated_ids,
        )

    async def compute_influence_edges(self, cycle_id: str, up_to_round: int, total_agents: int) -> dict[str, float]:
        return await schema_writes.compute_influence_edges(self._read, self._write, cycle_id, up_to_round, total_agents)

    async def write_shock_event(self, cycle_id: str, shock_text: str, injected_before_round: int) -> str:
        return await schema_writes.write_shock_event(self._write, cycle_id, shock_text, injected_before_round)

    async def write_decision_narrative(self, cycle_id: str, agent_id: str, narrative: str) -> None:
        await schema_writes.write_decision_narrative(self._write, cycle_id, agent_id, narrative)

    # --- analytics: report, shock and influence-edge reads (graph/analytics.py) ---

    async def read_consensus_summary(self, cycle_id: str) -> ConsensusSummaryRow:
        return await analytics.read_consensus_summary(self._read, cycle_id)

    async def read_round_timeline(self, cycle_id: str) -> list[RoundTimelineRow]:
        return await analytics.read_round_timeline(self._read, cycle_id)

    async def read_bracket_narratives(self, cycle_id: str) -> list[BracketNarrativeRow]:
        return await analytics.read_bracket_narratives(self._read, cycle_id)

    async def read_key_dissenters(self, cycle_id: str) -> list[KeyDissenterRow]:
        return await analytics.read_key_dissenters(self._read, cycle_id)

    async def read_influence_leaders(self, cycle_id: str, limit: int = 10) -> list[InfluenceLeaderRow]:
        return await analytics.read_influence_leaders(self._read, cycle_id, limit)

    async def read_signal_flips(self, cycle_id: str) -> list[SignalFlipRow]:
        return await analytics.read_signal_flips(self._read, cycle_id)

    async def read_entity_impact(self, cycle_id: str) -> list[EntityImpactRow]:
        return await analytics.read_entity_impact(self._read, cycle_id)

    async def read_final_round_decisions(self, cycle_id: str) -> list[FinalDecisionRow]:
        return await analytics.read_final_round_decisions(self._read, cycle_id)

    async def read_shock_impact(self, cycle_id: str) -> ShockImpactRow:
        return await analytics.read_shock_impact(self._read, cycle_id)

    async def read_shock_event(self, cycle_id: str) -> ShockEventRow | None:
        return await analytics.read_shock_event(self._read, cycle_id)

    async def read_influence_edges(self, cycle_id: str, round_num: int) -> list[InfluenceEdgeRow]:
        return await analytics.read_influence_edges(self._read, cycle_id, round_num)

    # --- replay, interview and cycle lookups (graph/replay_interview.py) ---

    async def read_full_cycle_signals(self, cycle_id: str) -> dict[tuple[str, int], AgentState]:
        return await replay_interview.read_full_cycle_signals(self._read, cycle_id)

    async def read_completed_cycles(
        self, limit: int = 20, *, before: datetime | None = None
    ) -> list[CompletedCycleRow]:
        return await replay_interview.read_completed_cycles(self._read, limit, before=before)

    async def read_bracket_narratives_for_round(self, cycle_id: str, round_num: int) -> list[BracketRoundRow]:
        return await replay_interview.read_bracket_narratives_for_round(self._read, cycle_id, round_num)

    async def read_rationale_entries_for_round(
        self, cycle_id: str, round_num: int, limit: int = 10
    ) -> list[RationaleRoundRow]:
        return await replay_interview.read_rationale_entries_for_round(self._read, cycle_id, round_num, limit)

    async def read_agent_interview_rows(self, agent_id: str, cycle_id: str) -> AgentInterviewRows:
        return await replay_interview.read_agent_interview_rows(self._read, agent_id, cycle_id)

    async def read_persona_trait_seed(self, cycle_id: str) -> int | None:
        return await replay_interview.read_persona_trait_seed(self._read, cycle_id)

    async def read_agent_decisions(self, cycle_id: str, agent_id: str) -> list[AgentDecisionRow]:
        return await replay_interview.read_agent_decisions(self._read, cycle_id, agent_id)

    async def read_decision_narrative(self, cycle_id: str, agent_id: str) -> str | None:
        return await replay_interview.read_decision_narrative(self._read, cycle_id, agent_id)

    async def read_cycle_status(self, cycle_id: str) -> CycleStatus | None:
        return await replay_interview.read_cycle_status(self._read, cycle_id)

    async def cycle_exists(self, cycle_id: str) -> bool:
        return await replay_interview.cycle_exists(self._read, cycle_id)

    async def read_latest_cycle_id(self, *, statuses: Collection[CycleStatus] = _COMPLETE_ONLY) -> str | None:
        return await replay_interview.read_latest_cycle_id(self._read, statuses=statuses)

    async def read_cycle_seed(self, cycle_id: str) -> str | None:
        return await replay_interview.read_cycle_seed(self._read, cycle_id)

    async def read_cycle_entities(self, cycle_id: str) -> list[EntityRef]:
        return await replay_interview.read_cycle_entities(self._read, cycle_id)
