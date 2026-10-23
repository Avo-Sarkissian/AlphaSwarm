"""Advisory synthesis engine — single orchestrator LLM call over prefetched swarm data.

Lifecycle note: this module does NOT load or unload the orchestrator model.
The model load/unload is handled by the caller
(alphaswarm.web.routes.advisory._run_advisory_synthesis,
docs/DECISIONS.md#p41-d-08) so the library stays infrastructure-free and
unit-testable with Fakes.

Pitfall 1: NEVER pass the PortfolioSnapshot or Holding objects into a structlog
event_dict. Log only scalar metadata (cycle_id, holdings_count, affected).
Pitfall 2: NEVER json.dumps over raw Decimal. All holdings values are stringified
before prompt construction.
Pitfall 3: one bounded retry on ValidationError; second failure raises.
Pitfall 4: NEVER log or forward str(ValidationError): it echoes the model's input
values, which can include tickers or a cost basis. Use validation_error_summary().
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
from alphaswarm.advisory.sector_map import EMPTY_SECTOR_MAP, UNKNOWN_SECTOR, SectorMap
from alphaswarm.advisory.types import AdvisoryItem, AdvisoryReport
from alphaswarm.holdings.types import PortfolioSnapshot
from alphaswarm.inference.types import InferenceMessage
from alphaswarm.logging import (
    validation_error_details,
    validation_error_location,
    validation_error_summary,
)

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.provider import InferenceProvider

log = structlog.get_logger(component="advisory")


def _enrich_holdings(
    holdings: list[dict[str, str]],
    entity_impacts: dict[str, float],
    seed_text: str,
    *,
    sector_map: SectorMap = EMPTY_SECTOR_MAP,
) -> list[dict[str, str]]:
    """Add sector fields + relevance_score to each holding; sort DESC by relevance.

    Relevance score = |entity_impact| * |macro_beta| + 0.5 * seed_match, where
    seed_match is 1.0 when the ticker or the sector label appears in the seed text
    as a whole word. The 'unknown' placeholder sector never matches: it would
    reward any rumor that mentions "unknown sources"
    (docs/DECISIONS.md#adr-advisory-pipeline).
    """
    enriched: list[dict[str, str]] = []
    for h in holdings:
        ticker = str(h.get("ticker", "")).upper()
        sm = sector_map.lookup(ticker)
        entity_impact = float(entity_impacts.get(ticker, 0.0))
        # Whole-word matches only: a short ticker or a one-word sector label is
        # often an ordinary English word inside the rumor text (docs/DECISIONS.md#f-28).
        sector_phrase = "" if sm["sector"] == UNKNOWN_SECTOR["sector"] else sm["sector"].replace("_", " ")
        seed_match = (
            1.0
            if (ticker and re.search(rf"\b{re.escape(ticker)}\b", seed_text, re.IGNORECASE))
            or (sector_phrase and re.search(rf"\b{re.escape(sector_phrase)}\b", seed_text, re.IGNORECASE))
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


def _ticker_entries(portfolio: PortfolioSnapshot) -> list[dict[str, str]]:
    """One prompt entry per unique held ticker (lots aggregated), first-seen order.

    Only the ticker reaches the LLM: quantities, cost basis and account data stay
    server-side (docs/DECISIONS.md#p41-d-05). The display casing is the first
    lot's, matching how the padded HOLD items are labelled.
    """
    display_by_ticker: dict[str, str] = {}
    for holding in portfolio.holdings:
        display_by_ticker.setdefault(holding.ticker.upper(), holding.ticker)
    return [{"ticker": display} for display in display_by_ticker.values()]


async def synthesize(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    graph_manager: GraphStateManager,
    provider: InferenceProvider,
    sector_map: SectorMap | None = None,
) -> AdvisoryReport:
    """Prefetch swarm data, call orchestrator once, parse + rank.

    *sector_map* comes from load_sector_map(settings.sector_map_path); None uses
    EMPTY_SECTOR_MAP (every holding gets the 'unknown' sector).

    Raises:
        pydantic.ValidationError: if the LLM returns a malformed payload twice.
        Any exception from graph_manager or the provider propagates unchanged so the
        advisory job's done-callback can record it in app.state.advisory_generation_error
        (docs/DECISIONS.md#p41-d-13).
    """
    log.info(
        "advisory_synthesize_start",
        cycle_id=cycle_id,
        holdings_count=len(portfolio.holdings),
    )
    smap = sector_map if sector_map is not None else EMPTY_SECTOR_MAP
    held = {h.ticker.upper() for h in portfolio.holdings}

    # Prefetch all four swarm payloads in parallel (docs/DECISIONS.md#p41-d-04).
    bracket_summary, timeline, narratives, entities = await asyncio.gather(
        graph_manager.read_consensus_summary(cycle_id),
        graph_manager.read_round_timeline(cycle_id),
        graph_manager.read_bracket_narratives(cycle_id),
        graph_manager.read_entity_impact(cycle_id),
    )

    # The seed rumor only adds context; a failed read must not block the advisory.
    seed_rumor = ""
    try:
        seed_rumor = await graph_manager.read_cycle_seed(cycle_id) or ""
    except Exception:  # noqa: BLE001 - synthesize still runs without seed text
        log.warning("advisory_seed_fetch_failed", cycle_id=cycle_id)

    _total_cb = sum((h.cost_basis if h.cost_basis is not None else Decimal("0")) for h in portfolio.holdings)
    # The ranking denominator must be POSITIVE (docs/DECISIONS.md#p41-d-07). The old
    # `or Decimal("1")` only caught a falsy (zero) sum; a NEGATIVE aggregate
    # (data-entry error or a credit/short lot) is truthy and would divide positive
    # exposures by a negative number, inverting the advisory ranking
    # (docs/DECISIONS.md#f-29).
    total_cost_basis = _total_cb if _total_cb > 0 else Decimal("1")

    # read_entity_impact rows carry entity_name + avg_sentiment. Collapse them to
    # {ticker: impact}, using avg_sentiment as the bounded [-1, 1] directional
    # magnitude. Entity names resolve only to HELD tickers (pass-through, or a
    # curated alias from the local sector map); anything else is skipped so it
    # cannot score an unrelated holding (docs/DECISIONS.md#f-07). When two
    # entities map to one ticker, keep the strongest.
    entity_impacts: dict[str, float] = {}
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        raw_name = str(entry.get("entity_name") or entry.get("entity") or "").strip()
        ticker = smap.resolve_ticker(raw_name, held) if raw_name else None
        if ticker is None:
            continue
        try:
            impact = float(entry.get("avg_sentiment", 0.0))
        except (TypeError, ValueError):
            impact = 0.0
        if ticker not in entity_impacts or abs(impact) > abs(entity_impacts[ticker]):
            entity_impacts[ticker] = impact

    enriched = _enrich_holdings(_ticker_entries(portfolio), entity_impacts, seed_rumor, sector_map=smap)
    top_holdings = enriched[:15]
    # docs/DECISIONS.md#sweep-b-7: do NOT send rest holdings to the LLM. They're padded
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
        provider=provider,
        messages=messages,
    )

    # Coverage is keyed by unique upper-cased ticker, not by Holding row: the
    # portfolio holds one Holding per lot, and a ticker can sit in two accounts.
    # Aggregate cost basis across lots per ticker.
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
        # Normalize the ticker to the portfolio's canonical casing — the LLM
        # may echo a different case ("zzzt") than the user's CSV, which would
        # make kept (conviction) and padded (HOLD) items disagree on casing for
        # the same position and break ticker-keyed lookups/dedupe
        # (docs/DECISIONS.md#f-30).
        # display_ticker[ticker_up] is guaranteed present because actual_exposure
        # (from cost_by_ticker, populated in the same loop) is not None here.
        kept_by_ticker[ticker_up] = it.model_copy(
            update={
                "ticker": display_ticker[ticker_up],
                "position_exposure": actual_exposure,
            }
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
    # (docs/DECISIONS.md#quick-260512-jqn) — we keep the contract, we just stop
    # spending LLM tokens on it.
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

    # Rerank by score = confidence × (exposure / total_cost_basis), desc
    # (docs/DECISIONS.md#p41-d-07).
    # Padded placeholders sort AFTER conviction items regardless of score —
    # effective sort key is (is_padded, -score).
    def _score(it: AdvisoryItem) -> float:
        return float(it.confidence) * (float(it.position_exposure) / float(total_cost_basis))

    conviction_items.sort(key=_score, reverse=True)
    padded_items.sort(key=_score, reverse=True)
    ranked = tuple(conviction_items + padded_items)

    # `affected_holdings` counts only items the LLM had real conviction on —
    # NOT the server-padded HOLD placeholders.
    affected_count = sum(1 for it in conviction_items if it.consensus_signal != "HOLD" or it.confidence > 0.4)

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


def _retry_feedback(exc: ValidationError) -> str:
    """Which fields failed and why, without echoing the values the model sent."""
    errors = validation_error_details(exc)
    return "\n".join(f"- {validation_error_location(error)}: {error['msg']}" for error in errors[:10])


async def _infer_with_retry(
    *,
    provider: InferenceProvider,
    messages: list[InferenceMessage],
) -> AdvisoryReport:
    """Call the orchestrator with json_mode=True; retry once on ValidationError.

    Pitfall 3: bounded retry. On the second ValidationError we raise.
    """
    result = await provider.chat(messages, json_mode=True)
    content = result.content or "{}"

    try:
        return AdvisoryReport.model_validate_json(content)
    except ValidationError as first_err:
        log.warning("advisory_validation_retry", **validation_error_summary(first_err))
        retry_messages: list[InferenceMessage] = [
            *messages,
            {
                "role": "user",
                "content": (
                    "Your previous response failed validation:\n"
                    f"{_retry_feedback(first_err)}\n"
                    "Return ONLY the JSON object matching the schema."
                ),
            },
        ]
        retry_result = await provider.chat(retry_messages, json_mode=True)
        retry_content = retry_result.content or "{}"
        return AdvisoryReport.model_validate_json(retry_content)
