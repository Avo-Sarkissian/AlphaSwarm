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
    BracketType,
    EntityType,
    ExtractedTicker,
    ParsedModifiersResult,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
    TickerDecision,
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


def _lenient_parse_ticker_decisions(raw_list: list) -> list[TickerDecision]:
    """Parse ticker_decisions leniently: drop invalid entries, keep valid ones.

    Addresses Codex review blocker #4: malformed nested values in ticker_decisions
    should not collapse the entire AgentDecision to PARSE_ERROR. Individual invalid
    entries are dropped with a debug log.
    """
    valid: list[TickerDecision] = []
    for item in raw_list:
        try:
            valid.append(TickerDecision.model_validate(item))
        except (ValidationError, TypeError, ValueError):
            logger.debug("ticker_decision_dropped", item=str(item)[:100])
            continue
    return valid


def _try_lenient_agent_parse(text: str, parse_tier: int) -> AgentDecision | None:
    """Try lenient parsing: pop ticker_decisions, validate base, merge back.

    Phase 18: Full model_validate_json may fail due to malformed ticker_decisions
    while top-level fields are valid. This pops ticker_decisions, validates the
    rest as AgentDecision (which works because ticker_decisions defaults to []),
    then leniently parses the popped ticker_decisions and merges back.
    """
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or "ticker_decisions" not in data:
            return None
        td_raw = data.pop("ticker_decisions")
        base = AgentDecision.model_validate(data)
        parsed_tds = _lenient_parse_ticker_decisions(td_raw if isinstance(td_raw, list) else [])
        result = base.model_copy(update={"ticker_decisions": parsed_tds})
        logger.debug(
            "parse_succeeded_lenient",
            parse_tier=parse_tier,
            signal=result.signal.value,
            ticker_decisions_kept=len(parsed_tds),
        )
        return result
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None


def parse_agent_decision(raw: str) -> AgentDecision:
    """Parse raw LLM output into a validated AgentDecision.

    Tries 3 tiers in order:
    1. Direct JSON validation via Pydantic model_validate_json()
    2. Code-fence stripping + regex extraction of JSON block, then validate
    3. PARSE_ERROR fallback with truncated raw content

    Each tier also attempts lenient parsing of ticker_decisions when strict
    validation fails (Phase 18: malformed nested fields should not collapse
    the entire decision to PARSE_ERROR).

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
        # Phase 18: Try lenient parse for malformed ticker_decisions
        lenient = _try_lenient_agent_parse(raw, parse_tier=1)
        if lenient is not None:
            return lenient

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
        lenient = _try_lenient_agent_parse(cleaned, parse_tier=2)
        if lenient is not None:
            return lenient

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
            lenient = _try_lenient_agent_parse(match.group(), parse_tier=2)
            if lenient is not None:
                return lenient

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
                lenient = _try_lenient_agent_parse(match.group(), parse_tier=2)
                if lenient is not None:
                    return lenient

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

        # Phase 18: Parse tickers from orchestrator response (Codex blocker #3)
        raw_tickers = data.get("tickers", [])
        tickers: list[ExtractedTicker] = []
        if isinstance(raw_tickers, list):
            for t in raw_tickers:
                try:
                    tickers.append(ExtractedTicker.model_validate(t))
                except (ValidationError, TypeError):
                    continue
        # Cap at 3 tickers, sorted by relevance descending (Phase 16 TICK-03)
        tickers = sorted(tickers, key=lambda t: t.relevance, reverse=True)[:3]

        overall_sentiment = float(data.get("overall_sentiment", 0.0))
        return SeedEvent(
            raw_rumor=original_rumor,
            entities=entities,
            overall_sentiment=overall_sentiment,
            tickers=tickers,
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


# ---------------------------------------------------------------------------
# Modifier response parsing (Phase 13)
# ---------------------------------------------------------------------------


def parse_modifier_response(raw: str) -> ParsedModifiersResult:
    """Parse orchestrator modifier JSON with 3-tier fallback (D-05, D-07, D-08).

    Expected JSON format: {"quants": "modifier string", ..., "whales": "modifier string"}
    Exactly 10 keys matching BracketType enum values.

    Tier 1: Direct JSON parse
    Tier 2: Code-fence strip / regex extraction
    Tier 3: Full fallback to static BRACKET_MODIFIERS[bracket][0]

    Missing or invalid keys trigger per-bracket fallback from static BRACKET_MODIFIERS (D-08).
    All dict keys are lowercased before validation (Pitfall 5: case insensitivity).
    """
    # Local import to avoid circular dependency (config.py imports from types.py)
    from alphaswarm.config import BRACKET_MODIFIERS, _truncate_modifier

    def _validate_and_fill(data: dict) -> dict[BracketType, str] | None:
        if not isinstance(data, dict):
            return None
        # Lowercase all keys (Pitfall 5)
        normalized = {k.lower().strip(): v for k, v in data.items() if isinstance(k, str)}
        result: dict[BracketType, str] = {}
        for bt in BracketType:
            val = normalized.get(bt.value)
            if isinstance(val, str) and val.strip():
                result[bt] = _truncate_modifier(val.strip())
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
    cleaned = _strip_code_fences(raw)
    for text in (cleaned, raw) if cleaned != raw else (cleaned,):
        try:
            data = json.loads(text)
            modifiers = _validate_and_fill(data)
            if modifiers is not None:
                logger.debug("modifier_parse_succeeded", parse_tier=2)
                return ParsedModifiersResult(modifiers=modifiers, parse_tier=2)
        except (json.JSONDecodeError, ValueError):
            pass
        match = _JSON_BLOCK_RE.search(text)
        if match:
            try:
                data = json.loads(match.group())
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
