"""Round 1 simulation pipeline for AlphaSwarm.

Composes inject_seed, dispatch_wave, and write_decisions into a single
end-to-end pipeline. run_round1() owns: seed injection -> model cleanup ->
governor start -> worker dispatch -> persistence -> cleanup.

CLI handler owns: AppState creation, schema setup, report printing, graph close.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import structlog

from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.config import persona_to_worker_config
from alphaswarm.seed import inject_seed
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings
    from alphaswarm.governor import ResourceGovernor
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.types import AgentDecision, AgentPersona, ParsedSeedResult

logger = structlog.get_logger(component="simulation")


@dataclasses.dataclass(frozen=True)
class Round1Result:
    """Immutable result container for the Round 1 pipeline.

    agent_decisions is the single canonical collection. Use it
    to derive decisions list when needed (no redundant field).
    """

    cycle_id: str
    parsed_result: ParsedSeedResult
    agent_decisions: list[tuple[str, AgentDecision]]


async def run_round1(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
) -> Round1Result:
    """Execute the Round 1 simulation pipeline.

    Pipeline steps:
    1. inject_seed (orchestrator model lifecycle is self-contained)
    2. ensure_clean_state (defensive cleanup after orchestrator)
    3. start_monitoring (governor RAM monitoring)
    4. load worker model
    5. dispatch_wave with peer_context=None (Round 1 = no peer influence)
    6. Positional assertion (dispatch results must match persona count)
    7. Pair agent IDs with decisions
    8. write_decisions with round_num=1
    9. Cleanup: unload worker (inner finally), stop monitoring (outer finally)

    Args:
        rumor: Raw seed rumor text.
        settings: Application settings.
        ollama_client: OllamaClient for inference.
        model_manager: Model lifecycle manager.
        graph_manager: Neo4j graph state manager.
        governor: ResourceGovernor for concurrency control.
        personas: List of AgentPersona to dispatch.

    Returns:
        Round1Result with cycle_id, parsed_result, and agent_decisions.
    """
    logger.info("round1_start", agent_count=len(personas))

    # 1. Inject seed (orchestrator model lifecycle is self-contained)
    cycle_id, parsed_result = await inject_seed(
        rumor, settings, ollama_client, model_manager, graph_manager,
    )

    # 2. Defensive model cleanup (review concern #4)
    await model_manager.ensure_clean_state()

    worker_alias = settings.ollama.worker_model_alias

    # 3. Start governor monitoring (review concern #1 -- must happen before dispatch)
    await governor.start_monitoring()
    try:
        # 4. Load worker model
        await model_manager.load_model(worker_alias)
        try:
            # 5. Convert personas and dispatch
            worker_configs = [persona_to_worker_config(p) for p in personas]
            decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                client=ollama_client,
                model=worker_alias,
                user_message=rumor,
                settings=settings.governor,
                peer_context=None,
            )

            # 6. Positional alignment assertion (review concern #3)
            assert len(decisions) == len(worker_configs), (
                f"dispatch_wave returned {len(decisions)} results "
                f"for {len(worker_configs)} personas"
            )

            # 7. Pair agent IDs with decisions
            agent_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec)
                for wc, dec in zip(worker_configs, decisions)
            ]

            # 8. Persist to Neo4j
            await graph_manager.write_decisions(
                agent_decisions, cycle_id, round_num=1,
            )
        finally:
            # 9a. Always unload worker model (inner finally)
            await model_manager.unload_model(worker_alias)
    finally:
        # 9b. Always stop governor monitoring (outer finally)
        await governor.stop_monitoring()

    # 10. Log completion and return
    error_count = sum(
        1 for _, d in agent_decisions if d.signal == SignalType.PARSE_ERROR
    )
    logger.info(
        "round1_complete",
        cycle_id=cycle_id,
        decision_count=len(agent_decisions),
        parse_error_count=error_count,
    )

    return Round1Result(
        cycle_id=cycle_id,
        parsed_result=parsed_result,
        agent_decisions=agent_decisions,
    )
