"""Seed injection pipeline for AlphaSwarm.

Orchestrates: prepare orchestrator provider -> parse seed rumor -> generate persona modifiers ->
persist to Neo4j -> teardown provider.
Called by CLI inject subcommand. Self-contained model lifecycle per D-07.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from alphaswarm.errors import StructuredOutputError
from alphaswarm.inference.structured import chat_structured
from alphaswarm.personas import BRACKET_MODIFIERS, compute_prompt_template_hash, load_bracket_configs
from alphaswarm.prompts.modifiers import (
    MODIFIER_GENERATION_PROMPT,
    build_modifier_user_message,
    truncate_modifier,
)
from alphaswarm.types import (
    BracketType,
    ParsedModifiersResult,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    normalize_signed_unit,
)

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.settings import AppSettings

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


class SeedLLMOutput(BaseModel):
    """The orchestrator's seed reply.

    Lenient on purpose: extra keys are ignored, an entity that fails validation
    is dropped instead of failing the reply, and numbers are clamped by the
    ``SeedEntity`` validators (docs/DECISIONS.md#adr-structured-output).
    ``overall_sentiment`` carries ``SeedEvent``'s range: clamping cannot fix
    NaN, so it must fail here, where chat_structured retries and falls back,
    and never later in ``to_seed_event``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    entities: list[SeedEntity]
    overall_sentiment: float = Field(ge=-1.0, le=1.0)

    @field_validator("entities", mode="before")
    @classmethod
    def _drop_invalid_entities(cls, value: object) -> object:
        if not isinstance(value, list):
            return value  # null or a non-list fails validation and triggers the retry
        kept: list[SeedEntity] = []
        for item in value:
            try:
                kept.append(SeedEntity.model_validate(item))
            except ValidationError:
                continue
        return kept

    @field_validator("overall_sentiment", mode="before")
    @classmethod
    def _clamp_sentiment(cls, value: object) -> object:
        return normalize_signed_unit(value)

    def to_seed_event(self, raw_rumor: str) -> SeedEvent:
        """Domain event; ``raw_rumor`` always comes from the caller, never the model."""
        return SeedEvent(
            raw_rumor=raw_rumor,
            entities=list(self.entities),
            overall_sentiment=self.overall_sentiment,
        )


def static_modifiers() -> dict[BracketType, str]:
    """Each bracket's first static modifier: the tier-3 fallback (docs/DECISIONS.md#p13-d-07)."""
    return {bracket: (BRACKET_MODIFIERS.get(bracket) or [""])[0] for bracket in BracketType}


class ModifiersLLMOutput(BaseModel):
    """The orchestrator's modifier reply: one short persona modifier per bracket.

    Keys are case-insensitive, extra keys are ignored and a missing or
    non-string value becomes "" so that bracket falls back to its static
    modifier (docs/DECISIONS.md#p13-d-08).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    institutions: str = ""
    sell_side: str = ""
    event_driven: str = ""
    quants: str = ""
    degens: str = ""
    narrators: str = ""
    algos: str = ""
    macro: str = ""
    shorts: str = ""
    allocators: str = ""

    @model_validator(mode="before")
    @classmethod
    def _lower_case_keys(cls, data: object) -> object:
        if isinstance(data, dict):
            return {(key.strip().lower() if isinstance(key, str) else key): value for key, value in data.items()}
        return data

    @field_validator("*", mode="before")
    @classmethod
    def _text_or_empty(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else ""

    def to_modifiers(self) -> tuple[dict[BracketType, str], list[str]]:
        """Bracket -> truncated modifier, plus the bracket values that fell back."""
        fallback = static_modifiers()
        modifiers: dict[BracketType, str] = {}
        fell_back: list[str] = []
        for bracket in BracketType:
            text = getattr(self, bracket.value)
            if text:
                modifiers[bracket] = truncate_modifier(text)
            else:
                modifiers[bracket] = fallback[bracket]
                fell_back.append(bracket.value)
        return modifiers, fell_back


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
        # 2-3. One schema-constrained call with parse fallbacks and one retry
        # (docs/DECISIONS.md#adr-structured-output); think=False stays inside the
        # Ollama adapter (docs/DECISIONS.md#adr-think-off).
        try:
            structured = await chat_structured(
                orchestrator,
                [
                    {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                    {"role": "user", "content": rumor},
                ],
                SeedLLMOutput,
            )
        except StructuredOutputError:
            logger.warning("seed_parse_used_fallback", parse_tier=3)
            parsed_result = ParsedSeedResult(
                seed_event=SeedEvent(raw_rumor=rumor, entities=[], overall_sentiment=0.0),
                parse_tier=3,
            )
        else:
            parsed_result = ParsedSeedResult(
                seed_event=structured.value.to_seed_event(rumor),
                parse_tier=structured.parse_tier,
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
    """Generate entity-aware bracket modifiers via the orchestrator (docs/DECISIONS.md#p13-d-04).

    One ``chat_structured`` call in the seed's orchestrator session
    (docs/DECISIONS.md#p13-d-06); a reply that never validates falls back to
    the static modifiers (tier 3, docs/DECISIONS.md#p13-d-07).
    """
    logger.info("modifier_generation_start", entity_count=len(seed_event.entities))
    try:
        result = await chat_structured(
            orchestrator,
            [
                {"role": "system", "content": MODIFIER_GENERATION_PROMPT},
                {"role": "user", "content": build_modifier_user_message(seed_event)},
            ],
            ModifiersLLMOutput,
        )
    except StructuredOutputError:
        logger.warning("modifier_generation_fallback", parse_tier=3)
        return ParsedModifiersResult(modifiers=static_modifiers(), parse_tier=3)
    modifiers, fell_back = result.value.to_modifiers()
    for bracket_value in fell_back:
        logger.warning("modifier_bracket_fallback", bracket=bracket_value, reason="missing_or_invalid")
    logger.info(
        "modifier_generation_complete",
        parse_tier=result.parse_tier,
        modifier_count=len(modifiers) - len(fell_back),
    )
    return ParsedModifiersResult(modifiers=modifiers, parse_tier=result.parse_tier)
