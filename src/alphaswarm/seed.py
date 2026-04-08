"""Seed injection pipeline for AlphaSwarm.

Orchestrates: load orchestrator model -> parse seed rumor -> persist to Neo4j -> unload model.
Called by CLI inject subcommand. Self-contained model lifecycle per D-07.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

from alphaswarm.parsing import parse_seed_event
from alphaswarm.ticker_validator import get_ticker_validator

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.types import ParsedModifiersResult, ParsedSeedResult, SeedEvent

logger = structlog.get_logger(component="seed")

ORCHESTRATOR_SYSTEM_PROMPT = """You are a financial intelligence analyst. Given a market rumor, extract all named entities and assess sentiment.

For each entity, determine:
- name: The entity name (company, sector, or person)
- type: One of "company", "sector", or "person"
- relevance: How central this entity is to the rumor (0.0-1.0)
- sentiment: The rumor's implication for this entity (-1.0 bearish to 1.0 bullish)

Also determine overall_sentiment for the entire rumor (-1.0 to 1.0).

For each company entity, also extract its stock ticker symbol. Include a "tickers" array with:
- symbol: The stock exchange ticker (e.g., "AAPL", "TSLA", "MSFT")
- company_name: Full company name
- relevance: Same relevance score as the entity (0.0-1.0)

Only include tickers for publicly traded companies. Maximum 3 tickers, ordered by relevance.

Be thorough: extract ALL entities mentioned or strongly implied. Include sectors affected even if not named directly. Assign relevance based on centrality to the rumor's core claim.

Respond with JSON: {"entities": [...], "overall_sentiment": float, "tickers": [{"symbol": "AAPL", "company_name": "Apple Inc", "relevance": 0.9}]}"""


async def inject_seed(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    *,
    modifier_generator: Callable[[SeedEvent, OllamaClient, str], Awaitable[ParsedModifiersResult]] | None = None,
) -> tuple[str, ParsedSeedResult, ParsedModifiersResult | None]:
    """End-to-end seed injection pipeline. Returns (cycle_id, parsed_result, modifier_result).

    When modifier_generator is provided (Phase 13), calls it after seed parsing
    completes but before the orchestrator model is unloaded (D-06: same session).
    modifier_result is None when no callback is provided.

    Uses create_cycle_with_seed_event() for atomic Cycle+Entity persistence.
    """
    logger.info("seed_injection_start", rumor_preview=rumor[:100])

    # 1. Load orchestrator model (per D-07)
    orchestrator_alias = settings.ollama.orchestrator_model_alias
    await model_manager.load_model(orchestrator_alias)
    try:
        # 2. Chat with format="json" and think=True (per D-04, D-05)
        response = await ollama_client.chat(
            model=orchestrator_alias,
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": rumor},
            ],
            format="json",
            think=True,  # May be silently ignored per Pitfall 1; compensated by prompt
        )

        # Log thinking output if present (may be None per Pitfall 1)
        if response.message.thinking:
            logger.debug("orchestrator_thinking", thinking_preview=response.message.thinking[:200])
        else:
            logger.debug("orchestrator_thinking_suppressed", note="format=json may suppress think tokens")

        # 3. Parse with 3-tier fallback (per D-06), returns ParsedSeedResult
        raw_content = response.message.content or ""
        validator = await get_ticker_validator()
        parsed_result = parse_seed_event(raw_content, rumor, ticker_validator=validator)

        # Log warning on fallback (addresses review concern #1: silent parse failure)
        if parsed_result.parse_tier == 3:
            logger.warning(
                "seed_parse_used_fallback",
                parse_tier=3,
                raw_preview=raw_content[:300],
            )

        # 4. Persist to Neo4j atomically (addresses review concern #2: no orphan Cycles)
        cycle_id = await graph_manager.create_cycle_with_seed_event(
            rumor, parsed_result.seed_event,
        )

        # 5. Phase 13: Generate modifiers while orchestrator is still loaded (D-06)
        modifier_result: ParsedModifiersResult | None = None
        if modifier_generator is not None:
            modifier_result = await modifier_generator(
                parsed_result.seed_event,
                ollama_client,
                orchestrator_alias,
            )

        logger.info(
            "seed_injection_complete",
            cycle_id=cycle_id,
            entity_count=len(parsed_result.seed_event.entities),
            ticker_count=len(parsed_result.seed_event.tickers),
            dropped_ticker_count=len(parsed_result.dropped_tickers),
            overall_sentiment=parsed_result.seed_event.overall_sentiment,
            parse_tier=parsed_result.parse_tier,
            modifier_parse_tier=modifier_result.parse_tier if modifier_result else None,
        )
        return cycle_id, parsed_result, modifier_result

    finally:
        # 6. Always unload orchestrator model (per D-07)
        await model_manager.unload_model(orchestrator_alias)
