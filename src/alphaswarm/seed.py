"""Seed injection pipeline for AlphaSwarm.

Orchestrates: prepare orchestrator provider -> parse seed rumor -> generate persona modifiers ->
persist to Neo4j -> teardown provider.
Called by CLI inject subcommand. Self-contained model lifecycle per D-07.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from alphaswarm.parsing import parse_modifier_response, parse_seed_event
from alphaswarm.personas import compute_prompt_template_hash, load_bracket_configs
from alphaswarm.prompts.modifiers import MODIFIER_GENERATION_PROMPT, build_modifier_user_message

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.settings import AppSettings
    from alphaswarm.types import ParsedModifiersResult, ParsedSeedResult, SeedEvent

logger = structlog.get_logger(component="seed")

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are a financial intelligence analyst. Given a market rumor, extract all"
    " named entities and assess sentiment.\n"
    "\n"
    "For each entity, determine:\n"
    "- name: The entity name (company, sector, or person)\n"
    '- type: One of "company", "sector", or "person"\n'
    "- relevance: How central this entity is to the rumor (0.0-1.0)\n"
    "- sentiment: The rumor's implication for this entity (-1.0 bearish to 1.0 bullish)\n"
    "\n"
    "Also determine overall_sentiment for the entire rumor (-1.0 to 1.0).\n"
    "\n"
    "Be thorough: extract ALL entities mentioned or strongly implied. Include sectors"
    " affected even if not named directly. Assign relevance based on centrality to the"
    " rumor's core claim.\n"
    "\n"
    'Respond with JSON: {"entities": [...], "overall_sentiment": float}'
)


async def inject_seed(
    rumor: str,
    settings: AppSettings,
    orchestrator: InferenceProvider,
    graph_manager: GraphStateManager,
    *,
    modifier_generator: (Callable[[SeedEvent, InferenceProvider], Awaitable[ParsedModifiersResult]] | None) = None,
    prompt_template_hash: str | None = None,
) -> tuple[str, ParsedSeedResult, ParsedModifiersResult | None]:
    """End-to-end seed injection pipeline. Returns (cycle_id, parsed_result, modifier_result).

    When modifier_generator is provided (Phase 13), calls it after seed parsing and
    BEFORE the Cycle is persisted, in the same orchestrator session
    (docs/DECISIONS.md#p13-d-06), so a failure leaves no orphan Cycle.
    modifier_result is None when no callback is provided.

    prompt_template_hash: sha256 of the static persona prompt set; defaults to
    the configured brackets. It is stored on the Cycle with the generated
    modifiers (docs/DECISIONS.md#adr-neo4j-schema).

    Uses create_cycle_with_seed_event() for atomic Cycle+Entity persistence,
    after the orchestrator is released: nothing that can fail runs between
    the write and the return, so the caller learns the id of the ``running``
    Cycle it must later mark (docs/DECISIONS.md#adr-cycle-metrics).
    """
    logger.info("seed_injection_start", rumor_preview=rumor[:100])

    # 1. Load orchestrator model (per D-07)
    await orchestrator.prepare()
    try:
        # 2. Chat with json_mode=True, think=False (think=True added ~265s/call
        # with marginal quality gain on this workload; see
        # docs/DECISIONS.md#adr-think-off for revisit triggers and how to flip back).
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

        # 4. Generate modifiers while the orchestrator is still loaded, BEFORE
        #    persisting: a failed call must leave no orphan Cycle
        #    (docs/DECISIONS.md#p13-d-06).
        modifier_result: ParsedModifiersResult | None = None
        if modifier_generator is not None:
            modifier_result = await modifier_generator(
                parsed_result.seed_event,
                orchestrator,
            )
    finally:
        # 5. Always unload orchestrator model (per D-07)
        await orchestrator.teardown()

    # 6. Persist Cycle + Entities atomically; the Cycle starts as "running". Last,
    #    so a failed or cancelled teardown leaves no Cycle that no run will ever
    #    mark failed or cancelled (docs/DECISIONS.md#adr-cycle-metrics).
    cycle_id = await graph_manager.create_cycle_with_seed_event(
        rumor,
        parsed_result.seed_event,
        num_rounds=settings.num_rounds,
        modifiers=modifier_result.modifiers if modifier_result is not None else None,
        prompt_template_hash=(
            prompt_template_hash
            if prompt_template_hash is not None
            else compute_prompt_template_hash(load_bracket_configs())
        ),
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


async def generate_modifiers(
    seed_event: SeedEvent,
    orchestrator: InferenceProvider,
) -> ParsedModifiersResult:
    """Generate entity-aware bracket modifiers via orchestrator LLM (D-04, D-05, D-06).

    Makes a single JSON-mode chat call to the orchestrator (which must already
    be loaded) and parses the response with 3-tier fallback.

    Args:
        seed_event: Parsed seed event with entities and raw_rumor.
        orchestrator: Active InferenceProvider for the orchestrator role.
            The model must already be loaded (prepare() must have been called).

    Returns:
        ParsedModifiersResult with modifiers dict and parse_tier.
    """
    user_message = build_modifier_user_message(seed_event)

    logger.info("modifier_generation_start", entity_count=len(seed_event.entities))

    inference_result = await orchestrator.chat(
        messages=[
            {"role": "system", "content": MODIFIER_GENERATION_PROMPT},
            {"role": "user", "content": user_message},
        ],
        json_mode=True,
    )

    raw_content = inference_result.content
    result = parse_modifier_response(raw_content)

    if result.parse_tier == 3:
        logger.warning(
            "modifier_generation_fallback",
            parse_tier=3,
            raw_preview=raw_content[:300],
        )
    else:
        logger.info(
            "modifier_generation_complete",
            parse_tier=result.parse_tier,
            modifier_count=len(result.modifiers),
        )

    return result
