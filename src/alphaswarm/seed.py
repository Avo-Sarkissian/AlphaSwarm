"""Seed injection pipeline for AlphaSwarm.

Orchestrates: load orchestrator model -> parse seed rumor -> persist to Neo4j -> unload model.
Called by CLI inject subcommand. Self-contained model lifecycle per D-07.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from alphaswarm.parsing import parse_seed_event

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.types import ParsedSeedResult

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
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
) -> tuple[str, ParsedSeedResult]:
    """End-to-end seed injection pipeline. Returns (cycle_id, parsed_result).

    Uses create_cycle_with_seed_event() for atomic Cycle+Entity persistence
    (addresses review concern about orphan Cycle nodes from separate ops).
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

        logger.info(
            "seed_injection_complete",
            cycle_id=cycle_id,
            entity_count=len(parsed_result.seed_event.entities),
            overall_sentiment=parsed_result.seed_event.overall_sentiment,
            parse_tier=parsed_result.parse_tier,
        )
        return cycle_id, parsed_result

    finally:
        # 5. Always unload orchestrator model (per D-07)
        await model_manager.unload_model(orchestrator_alias)
