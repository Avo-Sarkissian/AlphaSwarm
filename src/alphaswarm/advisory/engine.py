"""ADVIS-01 synthesis engine — single orchestrator LLM call over prefetched swarm data.

Lifecycle note: this module does NOT load or unload the orchestrator model.
The model load/unload is handled by the caller (alphaswarm.web.routes.advisory._run_advisory_synthesis)
per D-08 so the library stays infrastructure-free and unit-testable with Fakes.

Pitfall 1: NEVER pass the PortfolioSnapshot or Holding objects into a structlog
event_dict. Log only scalar metadata (cycle_id, holdings_count, affected).
Pitfall 2: NEVER json.dumps over raw Decimal. All holdings values are stringified
before prompt construction.
Pitfall 3: one bounded retry on ValidationError; second failure raises.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.types import AdvisoryReport
from alphaswarm.holdings.types import PortfolioSnapshot

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="advisory")


async def synthesize(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    graph_manager: "GraphStateManager",
    ollama_client: "OllamaClient",
    orchestrator_model: str,
) -> AdvisoryReport:
    """Prefetch swarm data, call orchestrator once, parse + rank.

    Raises:
        pydantic.ValidationError: if the LLM returns a malformed payload twice.
        Any exception from graph_manager or ollama_client propagates unchanged
        so the 41-02 done_callback can record it to app.state.advisory_generation_error.
    """
    log.info(
        "advisory_synthesize_start",
        cycle_id=cycle_id,
        holdings_count=len(portfolio.holdings),
    )

    # D-04: prefetch all four swarm payloads in parallel.
    bracket_summary, timeline, narratives, entities = await asyncio.gather(
        graph_manager.read_consensus_summary(cycle_id),
        graph_manager.read_round_timeline(cycle_id),
        graph_manager.read_bracket_narratives(cycle_id),
        graph_manager.read_entity_impact(cycle_id),
    )

    # Seed rumor retrieval — if the graph manager exposes read_cycle_seed, use it;
    # otherwise fall back to empty string (Claude's Discretion per CONTEXT.md).
    seed_rumor = ""
    read_seed = getattr(graph_manager, "read_cycle_seed", None)
    if read_seed is not None:
        try:
            seed_rumor = await read_seed(cycle_id) or ""
        except Exception:  # noqa: BLE001 - defensive; synthesize still runs without seed text
            log.warning("advisory_seed_fetch_failed", cycle_id=cycle_id)

    # Pitfall 1+2: minimal dict serialization. Never pass the snapshot or account hash.
    holdings_context: list[dict[str, str]] = [
        {
            "ticker": h.ticker,
            "qty": str(h.qty),
            "cost_basis": str(h.cost_basis if h.cost_basis is not None else Decimal("0")),
        }
        for h in portfolio.holdings
    ]
    total_cost_basis = sum(
        (h.cost_basis if h.cost_basis is not None else Decimal("0"))
        for h in portfolio.holdings
    ) or Decimal("1")  # D-07 guard against /0

    messages = build_advisory_prompt(
        cycle_id=cycle_id,
        seed_rumor=seed_rumor,
        bracket_summary=bracket_summary,
        timeline=timeline,
        narratives=narratives,
        entity_impact=entities,
        holdings=holdings_context,
    )

    report = await _infer_with_retry(
        ollama_client=ollama_client,
        model=orchestrator_model,
        messages=messages,
    )

    # D-07: rerank by score = confidence × (exposure / total_cost_basis), desc.
    ranked = tuple(
        sorted(
            report.items,
            key=lambda it: float(it.confidence)
            * (float(it.position_exposure) / float(total_cost_basis)),
            reverse=True,
        )
    )

    final = report.model_copy(
        update={
            "items": ranked,
            "total_holdings": len(portfolio.holdings),
            "affected_holdings": len(ranked),
            "generated_at": datetime.now(UTC),
        }
    )

    log.info(
        "advisory_synthesize_complete",
        cycle_id=cycle_id,
        total=len(portfolio.holdings),
        affected=len(ranked),
    )
    return final


async def _infer_with_retry(
    *,
    ollama_client: "OllamaClient",
    model: str,
    messages: list[dict[str, str]],
) -> AdvisoryReport:
    """Call the orchestrator with format='json'; retry once on ValidationError.

    Pitfall 3: bounded retry. On the second ValidationError we raise.
    """
    response = await ollama_client.chat(model=model, messages=messages, format="json")
    content = response.message.content or "{}"

    try:
        return AdvisoryReport.model_validate_json(content)
    except ValidationError as first_err:
        log.warning(
            "advisory_validation_retry",
            cycle_id_hint="present_in_messages",
            error=str(first_err),
        )
        retry_messages: list[dict[str, str]] = [
            *messages,
            {
                "role": "user",
                "content": (
                    f"Your previous response failed validation: {first_err}. "
                    "Return ONLY the JSON object matching the schema."
                ),
            },
        ]
        retry_response = await ollama_client.chat(
            model=model, messages=retry_messages, format="json"
        )
        retry_content = retry_response.message.content or "{}"
        return AdvisoryReport.model_validate_json(retry_content)
