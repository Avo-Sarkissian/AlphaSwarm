"""ADVIS-01 synthesis engine: one orchestrator call over prefetched swarm data.

Lifecycle: this module never loads or unloads a model; its caller, the
advisory job, owns prepare/teardown (docs/DECISIONS.md#p41-d-08).

The orchestrator writes only ``AdvisoryLLMOutput`` (outlook + conviction items),
decoded through ``chat_structured`` with the tickers restricted to the ones in
the prompt and temperature 0.2; ``assemble_advisory_report`` builds everything
else server-side (docs/DECISIONS.md#adr-advisory-pipeline).

Pitfall 1: NEVER pass the PortfolioSnapshot or Holding objects into a structlog
event_dict. Log only scalar metadata (cycle_id, counts, hallucinated tickers).
Pitfall 2: NEVER json.dumps over raw Decimal.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import structlog

from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.sector_map import EMPTY_SECTOR_MAP, UNKNOWN_SECTOR, SectorMap
from alphaswarm.advisory.types import AdvisoryItem, AdvisoryLLMOutput, AdvisoryReport, AdvisoryStats
from alphaswarm.holdings.types import PortfolioSnapshot
from alphaswarm.inference.schema import to_portable_schema
from alphaswarm.inference.structured import chat_structured

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


ADVISORY_TEMPERATURE: Final = 0.2
ADVISORY_MAX_TOKENS: Final = 3000
_PLACEHOLDER_CONFIDENCE: Final = 0.30
_PLACEHOLDER_RATIONALE: Final = "Swarm produced no strong directional view this cycle."


def advisory_llm_schema(tickers: Sequence[str]) -> dict[str, Any]:
    """AdvisoryLLMOutput's schema with ``items[].ticker`` restricted to *tickers*."""
    allowed = sorted({ticker.upper() for ticker in tickers})
    if not allowed:
        raise ValueError("the advisory prompt must contain at least one ticker")
    schema = to_portable_schema(AdvisoryLLMOutput.model_json_schema())
    schema["properties"]["items"]["items"]["properties"]["ticker"] = {
        "type": "string",
        "enum": allowed,
    }
    return schema


def assemble_advisory_report(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    llm: AdvisoryLLMOutput,
    generated_at: datetime | None = None,
) -> AdvisoryReport:
    """Build the advisory the user sees from the model's conviction items.

    Keeps only held tickers (the model can still emit others), keeps the
    highest-confidence item per ticker in the portfolio's casing, sets exposure
    to the aggregated cost basis, pads every other holding as a HOLD@0.30
    placeholder (docs/DECISIONS.md#sweep-b-7), ranks by confidence x exposure /
    total cost basis with placeholders last (docs/DECISIONS.md#p41-d-07) and
    computes stats over conviction items only.
    """
    cost_by_ticker: dict[str, Decimal] = {}
    display_ticker: dict[str, str] = {}
    for holding in portfolio.holdings:
        key = holding.ticker.upper()
        cost = holding.cost_basis if holding.cost_basis is not None else Decimal("0")
        cost_by_ticker[key] = cost_by_ticker.get(key, Decimal("0")) + cost
        display_ticker.setdefault(key, holding.ticker)
    total_cost = sum(cost_by_ticker.values(), Decimal("0"))
    # A negative aggregate would invert the ranking (docs/DECISIONS.md#f-29).
    denominator = total_cost if total_cost > 0 else Decimal("1")

    kept: dict[str, AdvisoryItem] = {}
    dropped: list[str] = []
    for item in llm.items:
        key = item.ticker.upper()
        exposure = cost_by_ticker.get(key)
        if exposure is None:
            dropped.append(key)
            continue
        previous = kept.get(key)
        if previous is not None and previous.confidence >= item.confidence:
            continue
        # Portfolio casing, so kept and padded items agree (docs/DECISIONS.md#f-30).
        kept[key] = AdvisoryItem(
            ticker=display_ticker[key],
            consensus_signal=item.signal,
            confidence=item.confidence,
            rationale_summary=item.rationale,
            position_exposure=exposure,
            source="swarm",
            risk=item.risk,
            upside=item.upside,
        )
    if dropped:
        # Pitfall 1: ticker symbols of NON-held names only; never qty or cost basis.
        log.warning(
            "advisory_hallucinated_tickers_dropped",
            cycle_id=cycle_id,
            count=len(dropped),
            tickers=dropped,
        )

    placeholders = [
        AdvisoryItem(
            ticker=display_ticker[key],
            consensus_signal="HOLD",
            confidence=_PLACEHOLDER_CONFIDENCE,
            rationale_summary=_PLACEHOLDER_RATIONALE,
            position_exposure=exposure,
            source="placeholder",
        )
        for key, exposure in cost_by_ticker.items()
        if key not in kept
    ]

    def _score(item: AdvisoryItem) -> float:
        return float(item.confidence) * (float(item.position_exposure) / float(denominator))

    conviction = sorted(kept.values(), key=_score, reverse=True)
    ranked = tuple(conviction + sorted(placeholders, key=_score, reverse=True))
    return AdvisoryReport(
        cycle_id=cycle_id,
        generated_at=generated_at if generated_at is not None else datetime.now(UTC),
        portfolio_outlook=llm.portfolio_outlook,
        items=ranked,
        total_holdings=len(cost_by_ticker),
        affected_holdings=sum(1 for item in conviction if item.consensus_signal != "HOLD" or item.confidence > 0.4),
        stats=AdvisoryStats.from_items(ranked),
        holdings_as_of=portfolio.as_of,
    )


async def synthesize(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    graph_manager: GraphStateManager,
    provider: InferenceProvider,
    sector_map: SectorMap | None = None,
) -> AdvisoryReport:
    """Prefetch swarm data, call the orchestrator once, assemble the advisory.

    *sector_map* comes from load_sector_map(settings.sector_map_path); None uses
    EMPTY_SECTOR_MAP (every holding gets the 'unknown' sector).

    Raises:
        StructuredOutputError: if the orchestrator returns an invalid reply twice.
        ValueError: if the portfolio holds no tickers (the loader never returns one).
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

    result = await chat_structured(
        provider,
        messages,
        AdvisoryLLMOutput,
        schema=advisory_llm_schema([str(h["ticker"]) for h in top_holdings]),
        temperature=ADVISORY_TEMPERATURE,
        max_tokens=ADVISORY_MAX_TOKENS,
    )
    report = assemble_advisory_report(cycle_id=cycle_id, portfolio=portfolio, llm=result.value)
    log.info(
        "advisory_synthesize_complete",
        cycle_id=cycle_id,
        total=report.total_holdings,
        affected=report.affected_holdings,
        llm_items=len(result.value.items),
        padded_items=report.stats.placeholder_count if report.stats is not None else 0,
        parse_tier=result.parse_tier,
        attempts=result.attempts,
    )
    return report
