"""Seed injection pipeline for AlphaSwarm.

Orchestrates: prepare orchestrator provider -> parse seed rumor -> persist to Neo4j -> teardown provider.
Called by CLI inject subcommand. Self-contained model lifecycle per D-07.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

from alphaswarm.parsing import parse_seed_event

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.types import ParsedModifiersResult, ParsedSeedResult, SeedEvent

logger = structlog.get_logger(component="seed")

ORCHESTRATOR_SYSTEM_PROMPT = """You are a financial intelligence analyst. Given a market rumor, extract all named entities and assess sentiment.

For each entity, determine:
- name: The entity name (company, sector, or person)
- type: One of "company", "sector", or "person"
- relevance: How central this entity is to the rumor (0.0-1.0)
- sentiment: The rumor's implication for this entity (-1.0 bearish to 1.0 bullish)

Also determine overall_sentiment for the entire rumor (-1.0 to 1.0).

Be thorough: extract ALL entities mentioned or strongly implied. Include sectors affected even if not named directly. Assign relevance based on centrality to the rumor's core claim.

Respond with JSON: {"entities": [...], "overall_sentiment": float}"""


async def inject_seed(
    rumor: str,
    settings: AppSettings,
    orchestrator: InferenceProvider,
    graph_manager: GraphStateManager,
    *,
    modifier_generator: Callable[[SeedEvent, InferenceProvider], Awaitable[ParsedModifiersResult]] | None = None,
) -> tuple[str, ParsedSeedResult, ParsedModifiersResult | None]:
    """End-to-end seed injection pipeline. Returns (cycle_id, parsed_result, modifier_result).

    When modifier_generator is provided (Phase 13), calls it after seed parsing
    completes but before the orchestrator provider is torn down (D-06: same session).
    modifier_result is None when no callback is provided.

    Uses create_cycle_with_seed_event() for atomic Cycle+Entity persistence.
    """
    logger.info("seed_injection_start", rumor_preview=rumor[:100])

    # 1. Load orchestrator model (per D-07)
    await orchestrator.prepare()
    try:
        # 2. Chat with json_mode=True, think=False per Phase 41.4 decision
        # (think=True added ~265s/call with marginal quality gain on this workload;
        # see .planning/phases/41.4-r3-inference-and-ws-stall/41.4-MODEL-DECISION-LOG.md
        # for revisit triggers and how to flip back).
        inference_result = await orchestrator.chat(
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": rumor},
            ],
            json_mode=True,
        )

        # 3. Parse with 3-tier fallback (per D-06), returns ParsedSeedResult
        raw_content = inference_result.content
        parsed_result = parse_seed_event(raw_content, rumor)

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
                orchestrator,
            )

        logger.info(
            "seed_injection_complete",
            cycle_id=cycle_id,
            entity_count=len(parsed_result.seed_event.entities),
            overall_sentiment=parsed_result.seed_event.overall_sentiment,
            parse_tier=parsed_result.parse_tier,
            modifier_parse_tier=modifier_result.parse_tier if modifier_result else None,
        )
        return cycle_id, parsed_result, modifier_result

    finally:
        # 6. Always unload orchestrator model (per D-07)
        await orchestrator.teardown()
