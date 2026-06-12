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
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.sector_map import lookup as sector_lookup
from alphaswarm.advisory.types import AdvisoryReport
from alphaswarm.holdings.types import PortfolioSnapshot

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="advisory")


def _enrich_holdings(
    holdings: list[dict[str, str]],
    entity_impacts: dict[str, float],
    seed_text: str,
) -> list[dict[str, str]]:
    """Add sector_map fields + relevance_score to each holding; sort DESC by relevance.

    ITEM 6 of quick task 260512-jqn: produces the ordered list the prompt
    consumes — top N goes through with full enrichment, the rest with
    sector tag only.

    Relevance score = |entity_impact| * |macro_beta| + 0.5 * seed_match.
    seed_match is 1.0 when the ticker or its sector substring appears
    in the seed text, else 0.0.
    """
    seed_lower = seed_text.lower()
    enriched: list[dict[str, str]] = []
    for h in holdings:
        ticker = str(h.get("ticker", "")).upper()
        sm = sector_lookup(ticker)
        entity_impact = float(entity_impacts.get(ticker, 0.0))
        # Ticker match uses a word-boundary regex — a plain substring test
        # false-positives on short tickers ("ARM" in "pharma"). Sector names
        # are underscore_joined ("consumer_tech") and can never substring-match
        # prose, so compare with underscores replaced by spaces.
        sector_phrase = sm["sector"].replace("_", " ")
        seed_match = (
            1.0
            if (ticker and re.search(rf"\b{re.escape(ticker)}\b", seed_text, re.IGNORECASE))
            or (sector_phrase and sector_phrase in seed_lower)
            else 0.0
        )
        relevance = abs(entity_impact) * abs(sm["macro_beta"]) + 0.5 * seed_match
        enriched.append(
            {
                **h,
                # SectorInfo fields stringified for the JSON prompt payload.
                "sector": sm["sector"],
                "region_exposure": sm["region_exposure"],
                "supply_chain_sensitivity": sm["supply_chain_sensitivity"],
                "macro_beta": str(sm["macro_beta"]),
                "relevance_score": f"{relevance:.4f}",
            }
        )
    enriched.sort(key=lambda x: float(x["relevance_score"]), reverse=True)
    return enriched


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

    # ITEM 6 of quick task 260512-jqn — enrich + split.
    # entity_impact from Neo4j is a list[dict] where each entry has at least
    # `entity` and a magnitude-like field. We collapse to {ticker: float}
    # for the relevance scorer; missing tickers fall back to 0.0.
    entity_impacts: dict[str, float] = {}
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("entity") or entry.get("ticker") or "").upper()
        if not ticker:
            continue
        # Magnitude — try several known keys without over-specifying schema.
        mag_raw = (
            entry.get("magnitude")
            or entry.get("impact")
            or entry.get("score")
            or 0.0
        )
        try:
            entity_impacts[ticker] = float(mag_raw)
        except (TypeError, ValueError):
            entity_impacts[ticker] = 0.0

    enriched = _enrich_holdings(holdings_context, entity_impacts, seed_rumor)
    top_holdings = enriched[:15]
    # SWEEP-260528 B-7: do NOT send rest holdings to the LLM. They're padded
    # server-side with HOLD@0.30 after the conviction items return. Saves
    # ~1500 prompt tokens and ~25-30s synthesis time per cycle.

    messages = build_advisory_prompt(
        cycle_id=cycle_id,
        seed_rumor=seed_rumor,
        bracket_summary=bracket_summary,
        timeline=timeline,
        narratives=narratives,
        entity_impact=entities,
        top_holdings=top_holdings,
    )

    report = await _infer_with_retry(
        ollama_client=ollama_client,
        model=orchestrator_model,
        messages=messages,
    )

    # Local import: avoid circularity at module load.
    from alphaswarm.advisory.types import AdvisoryItem

    # Coverage is keyed by unique upper-cased TICKER, not by Holding row — the
    # portfolio holds one Holding per lot, and MRVL/QQQ appear in both taxable
    # and Roth accounts. Aggregate cost basis across lots per ticker.
    cost_by_ticker: dict[str, Decimal] = {}
    display_ticker: dict[str, str] = {}
    for h in portfolio.holdings:
        ticker_up = h.ticker.upper()
        cost = h.cost_basis if h.cost_basis is not None else Decimal("0")
        cost_by_ticker[ticker_up] = cost_by_ticker.get(ticker_up, Decimal("0")) + cost
        display_ticker.setdefault(ticker_up, h.ticker)

    # Keep only LLM items for tickers the user actually owns — the LLM can
    # hallucinate positions (with invented exposure) for tickers in the seed.
    # Dedupe LLM repeats per ticker (keep highest confidence) and overwrite
    # position_exposure with the aggregated ACTUAL cost basis.
    kept_by_ticker: dict[str, AdvisoryItem] = {}
    dropped_tickers: list[str] = []
    for it in report.items:
        ticker_up = it.ticker.upper()
        actual_exposure = cost_by_ticker.get(ticker_up)
        if actual_exposure is None:
            dropped_tickers.append(ticker_up)
            continue
        prev = kept_by_ticker.get(ticker_up)
        if prev is not None and prev.confidence >= it.confidence:
            continue
        kept_by_ticker[ticker_up] = it.model_copy(
            update={"position_exposure": actual_exposure}
        )
    if dropped_tickers:
        # Pitfall 1: scalar-only logging — ticker symbols are fine, never
        # qty/cost_basis/account fields.
        log.warning(
            "advisory_hallucinated_tickers_dropped",
            cycle_id=cycle_id,
            count=len(dropped_tickers),
            tickers=dropped_tickers,
        )

    # Pad: every unique ticker NOT covered by a kept LLM item becomes a
    # HOLD@0.30 placeholder so the frontend Holdings tab still shows the full
    # portfolio. The user explicitly asked for one-item-per-holding rendering
    # in 260512-jqn — we keep the contract, we just stop spending LLM tokens
    # on it.
    conviction_items: list[AdvisoryItem] = list(kept_by_ticker.values())
    padded_items: list[AdvisoryItem] = [
        AdvisoryItem(
            ticker=display_ticker[ticker_up],
            consensus_signal="HOLD",
            confidence=0.30,
            rationale_summary="Swarm produced no strong directional view this cycle.",
            position_exposure=exposure,
        )
        for ticker_up, exposure in cost_by_ticker.items()
        if ticker_up not in kept_by_ticker
    ]

    # D-07: rerank by score = confidence × (exposure / total_cost_basis), desc.
    # Padded placeholders sort AFTER conviction items regardless of score —
    # effective sort key is (is_padded, -score).
    def _score(it: AdvisoryItem) -> float:
        return float(it.confidence) * (float(it.position_exposure) / float(total_cost_basis))

    conviction_items.sort(key=_score, reverse=True)
    padded_items.sort(key=_score, reverse=True)
    ranked = tuple(conviction_items + padded_items)

    # `affected_holdings` counts only items the LLM had real conviction on —
    # NOT the server-padded HOLD placeholders.
    affected_count = sum(
        1 for it in conviction_items
        if it.consensus_signal != "HOLD" or it.confidence > 0.4
    )

    final = report.model_copy(
        update={
            "cycle_id": cycle_id,  # never trust the LLM-echoed value
            "items": ranked,
            "total_holdings": len(cost_by_ticker),  # unique tickers, not lots
            "affected_holdings": affected_count,
            "generated_at": datetime.now(UTC),
        }
    )

    log.info(
        "advisory_synthesize_complete",
        cycle_id=cycle_id,
        total=len(cost_by_ticker),
        affected=affected_count,
        llm_items=len(report.items),
        dropped_items=len(dropped_tickers),
        padded_items=len(padded_items),
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
    response = await ollama_client.chat(
        model=model, messages=messages, format="json", think=False
    )
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
            model=model, messages=retry_messages, format="json", think=False
        )
        retry_content = retry_response.message.content or "{}"
        return AdvisoryReport.model_validate_json(retry_content)
