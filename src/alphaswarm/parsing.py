"""Structured output parsing for LLM responses.

Implements the INFRA-08 3-tier fallback:
1. Tier 1 -- Native JSON mode: Direct Pydantic model_validate_json()
2. Tier 2 -- Regex extraction: Strip code fences, extract JSON block, then validate
3. Tier 3 -- PARSE_ERROR: Return AgentDecision with signal=PARSE_ERROR

Usage:
    decision = parse_agent_decision(response.message.content)
"""

from __future__ import annotations

import json
from typing import Literal

import structlog
from pydantic import ValidationError

from alphaswarm.inference.structured import json_object_candidates, strip_code_fences
from alphaswarm.personas import BRACKET_MODIFIERS
from alphaswarm.prompts.modifiers import truncate_modifier
from alphaswarm.types import (
    AgentDecision,
    BracketType,
    ErrorKind,
    ParsedModifiersResult,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)

logger = structlog.get_logger(component="parsing")


def _engine_fields(decision: AgentDecision, tier: Literal[1, 2]) -> AgentDecision:
    """Make ``error_kind`` and ``parse_tier`` engine-owned.

    A parse-error signal is classified ``("parse", 3)`` whatever the model echoed;
    any other decision carries the tier it was parsed at and no error kind
    (docs/DECISIONS.md#adr-structured-output).
    """
    wanted_kind: ErrorKind | None = "parse" if decision.signal is SignalType.PARSE_ERROR else None
    wanted_tier: Literal[1, 2, 3] = 3 if wanted_kind == "parse" else tier
    if decision.error_kind == wanted_kind and decision.parse_tier == wanted_tier:
        return decision
    return decision.model_copy(update={"error_kind": wanted_kind, "parse_tier": wanted_tier})


def parse_agent_decision(raw: str) -> AgentDecision:
    """Parse raw LLM output into a validated AgentDecision.

    Tries 3 tiers in order:
    1. Direct JSON validation via Pydantic model_validate_json()
    2. Code-fence stripping + regex extraction of JSON block, then validate
    3. PARSE_ERROR fallback with truncated raw content

    Args:
        raw: Raw string from LLM response (message.content).

    Returns:
        AgentDecision -- always returns, never raises.
    """
    # Tier 1: Direct JSON validation
    try:
        result = AgentDecision.model_validate_json(raw)
        logger.debug("parse succeeded", parse_tier=1, signal=result.signal.value)
        return _engine_fields(result, 1)
    except (ValidationError, ValueError):
        pass

    # Tier 2: Strip code fences, then regex extraction
    cleaned = strip_code_fences(raw)

    # Try direct parse on cleaned text (code fence removal may yield pure JSON)
    try:
        result = AgentDecision.model_validate_json(cleaned)
        logger.debug(
            "parse succeeded via code-fence stripping",
            parse_tier=2,
            signal=result.signal.value,
        )
        return _engine_fields(result, 2)
    except (ValidationError, ValueError):
        pass

    # Brace extraction on cleaned text (balanced scan first, greedy fallback)
    for candidate in json_object_candidates(cleaned):
        try:
            result = AgentDecision.model_validate_json(candidate)
            logger.debug(
                "parse succeeded via regex extraction",
                parse_tier=2,
                signal=result.signal.value,
            )
            return _engine_fields(result, 2)
        except (ValidationError, ValueError):
            pass

    # Also try extraction on original text (in case code fence stripping lost context)
    if cleaned != raw:
        for candidate in json_object_candidates(raw):
            try:
                result = AgentDecision.model_validate_json(candidate)
                logger.debug(
                    "parse succeeded via regex on original",
                    parse_tier=2,
                    signal=result.signal.value,
                )
                return _engine_fields(result, 2)
            except (ValidationError, ValueError):
                pass

    # Tier 3: PARSE_ERROR fallback, at WARNING so failures are visible
    logger.warning("decision_parse_failed", parse_tier=3, raw_preview=raw[:200])
    return AgentDecision(
        signal=SignalType.PARSE_ERROR,
        confidence=0.0,
        rationale=f"Parse failed: {raw[:200]}",
        error_kind="parse",
        parse_tier=3,
    )


# ---------------------------------------------------------------------------
# Seed event parsing (Phase 5)
# ---------------------------------------------------------------------------


def _try_parse_seed_json(text: str, original_rumor: str) -> SeedEvent | None:
    """Attempt to parse text as JSON into SeedEvent. Returns None on any failure."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    try:
        # Parse entities individually, skip invalid ones
        raw_entities = data.get("entities", [])
        if not isinstance(raw_entities, list):
            return None
        entities: list[SeedEntity] = []
        for e in raw_entities:
            try:
                entities.append(SeedEntity.model_validate(e))
            except (ValidationError, TypeError):
                continue

        overall_sentiment = float(data.get("overall_sentiment", 0.0))
        return SeedEvent(
            raw_rumor=original_rumor,
            entities=entities,
            overall_sentiment=overall_sentiment,
        )
    except (ValidationError, TypeError, ValueError, KeyError):
        return None


def parse_seed_event(raw: str, original_rumor: str) -> ParsedSeedResult:
    """Parse orchestrator output into SeedEvent with 3-tier fallback.

    Returns ParsedSeedResult with parse_tier metadata so callers can
    distinguish genuine empty extraction (tier 1/2) from parse failure (tier 3).

    Args:
        raw: Raw string from orchestrator LLM response (message.content).
        original_rumor: The original rumor text, injected as raw_rumor.

    Returns:
        ParsedSeedResult -- always returns, never raises.
    """
    # Tier 1: Direct JSON parse
    result = _try_parse_seed_json(raw, original_rumor)
    if result is not None:
        logger.debug("seed_parse_succeeded", parse_tier=1, entity_count=len(result.entities))
        return ParsedSeedResult(seed_event=result, parse_tier=1)

    # Tier 2: Strip code fences, then regex extraction
    cleaned = strip_code_fences(raw)
    # Try cleaned text directly
    result = _try_parse_seed_json(cleaned, original_rumor)
    if result is not None:
        logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
        return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Brace extraction on cleaned text (balanced scan first, greedy fallback)
    for candidate in json_object_candidates(cleaned):
        result = _try_parse_seed_json(candidate, original_rumor)
        if result is not None:
            logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
            return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Extraction on original text if different
    if cleaned != raw:
        for candidate in json_object_candidates(raw):
            result = _try_parse_seed_json(candidate, original_rumor)
            if result is not None:
                logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
                return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Tier 3: Fallback
    logger.debug("seed_parse_failed_all_tiers", parse_tier=3, raw_preview=raw[:500])
    return ParsedSeedResult(
        seed_event=SeedEvent(raw_rumor=original_rumor, entities=[], overall_sentiment=0.0),
        parse_tier=3,
    )


# ---------------------------------------------------------------------------
# Modifier response parsing (Phase 13)
# ---------------------------------------------------------------------------


def parse_modifier_response(raw: str) -> ParsedModifiersResult:
    """Parse orchestrator modifier JSON with 3-tier fallback (D-05, D-07, D-08).

    Expected JSON format: {"institutions": "modifier string", ..., "allocators": "modifier string"}
    Exactly 10 keys matching BracketType enum values.

    Tier 1: Direct JSON parse
    Tier 2: Code-fence strip / regex extraction
    Tier 3: Full fallback to static BRACKET_MODIFIERS[bracket][0]

    Missing or invalid keys trigger per-bracket fallback from static BRACKET_MODIFIERS (D-08).
    All dict keys are lowercased before validation (Pitfall 5: case insensitivity).
    """

    def _validate_and_fill(data: object) -> dict[BracketType, str] | None:
        if not isinstance(data, dict):
            return None
        # Lowercase all keys (Pitfall 5)
        normalized = {k.lower().strip(): v for k, v in data.items() if isinstance(k, str)}
        result: dict[BracketType, str] = {}
        for bt in BracketType:
            val = normalized.get(bt.value)
            if isinstance(val, str) and val.strip():
                result[bt] = truncate_modifier(val.strip())
            else:
                # Per-bracket fallback to static (D-08)
                static_mods = BRACKET_MODIFIERS.get(bt, [])
                result[bt] = static_mods[0] if static_mods else ""
                logger.warning(
                    "modifier_bracket_fallback",
                    bracket=bt.value,
                    reason="missing_or_invalid",
                )
        return result

    # Tier 1: Direct JSON parse
    try:
        data = json.loads(raw)
        modifiers = _validate_and_fill(data)
        if modifiers is not None:
            logger.debug("modifier_parse_succeeded", parse_tier=1)
            return ParsedModifiersResult(modifiers=modifiers, parse_tier=1)
    except (json.JSONDecodeError, ValueError):
        pass

    # Tier 2: Strip code fences, then regex extraction
    cleaned = strip_code_fences(raw)
    for text in (cleaned, raw) if cleaned != raw else (cleaned,):
        try:
            data = json.loads(text)
            modifiers = _validate_and_fill(data)
            if modifiers is not None:
                logger.debug("modifier_parse_succeeded", parse_tier=2)
                return ParsedModifiersResult(modifiers=modifiers, parse_tier=2)
        except (json.JSONDecodeError, ValueError):
            pass
        for candidate in json_object_candidates(text):
            try:
                data = json.loads(candidate)
                modifiers = _validate_and_fill(data)
                if modifiers is not None:
                    logger.debug("modifier_parse_succeeded", parse_tier=2)
                    return ParsedModifiersResult(modifiers=modifiers, parse_tier=2)
            except (json.JSONDecodeError, ValueError):
                pass

    # Tier 3: Full fallback to static BRACKET_MODIFIERS (D-07)
    logger.warning("modifier_parse_failed_all_tiers", parse_tier=3, raw_preview=raw[:500])
    fallback: dict[BracketType, str] = {}
    for bt in BracketType:
        static_mods = BRACKET_MODIFIERS.get(bt, [])
        fallback[bt] = static_mods[0] if static_mods else ""
    return ParsedModifiersResult(modifiers=fallback, parse_tier=3)
