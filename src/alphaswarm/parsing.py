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
import re

import structlog
from pydantic import ValidationError

from alphaswarm.types import (
    AgentDecision,
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)

logger = structlog.get_logger(component="parsing")

# Strip markdown code fences (```json ... ``` or ``` ... ```)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Extract a JSON object from text. Uses greedy match to capture nested structures.
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences, returning the inner content.

    If no code fences found, returns the original text unchanged.
    Addresses review concern: LLMs sometimes wrap JSON in markdown blocks.
    """
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


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
        return result
    except (ValidationError, ValueError):
        pass

    # Tier 2: Strip code fences, then regex extraction
    cleaned = _strip_code_fences(raw)

    # Try direct parse on cleaned text (code fence removal may yield pure JSON)
    try:
        result = AgentDecision.model_validate_json(cleaned)
        logger.debug(
            "parse succeeded via code-fence stripping",
            parse_tier=2,
            signal=result.signal.value,
        )
        return result
    except (ValidationError, ValueError):
        pass

    # Regex extraction on cleaned text
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        try:
            result = AgentDecision.model_validate_json(match.group())
            logger.debug(
                "parse succeeded via regex extraction",
                parse_tier=2,
                signal=result.signal.value,
            )
            return result
        except (ValidationError, ValueError):
            pass

    # Also try regex on original text (in case code fence stripping lost context)
    if cleaned != raw:
        match = _JSON_BLOCK_RE.search(raw)
        if match:
            try:
                result = AgentDecision.model_validate_json(match.group())
                logger.debug(
                    "parse succeeded via regex on original",
                    parse_tier=2,
                    signal=result.signal.value,
                )
                return result
            except (ValidationError, ValueError):
                pass

    # Tier 3: PARSE_ERROR fallback
    logger.debug(
        "parse failed at all tiers",
        parse_tier=3,
        raw_preview=raw[:500],
    )
    return AgentDecision(
        signal=SignalType.PARSE_ERROR,
        confidence=0.0,
        rationale=f"Parse failed: {raw[:200]}",
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
    cleaned = _strip_code_fences(raw)
    # Try cleaned text directly
    result = _try_parse_seed_json(cleaned, original_rumor)
    if result is not None:
        logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
        return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Regex extraction on cleaned text
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        result = _try_parse_seed_json(match.group(), original_rumor)
        if result is not None:
            logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
            return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Regex on original text if different
    if cleaned != raw:
        match = _JSON_BLOCK_RE.search(raw)
        if match:
            result = _try_parse_seed_json(match.group(), original_rumor)
            if result is not None:
                logger.debug("seed_parse_succeeded", parse_tier=2, entity_count=len(result.entities))
                return ParsedSeedResult(seed_event=result, parse_tier=2)

    # Tier 3: Fallback
    logger.debug("seed_parse_failed_all_tiers", parse_tier=3, raw_preview=raw[:500])
    return ParsedSeedResult(
        seed_event=SeedEvent(raw_rumor=original_rumor, entities=[], overall_sentiment=0.0),
        parse_tier=3,
    )
