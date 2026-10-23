"""Structured output parsing for LLM responses.

Implements the INFRA-08 3-tier fallback:
1. Tier 1 -- Native JSON mode: Direct Pydantic model_validate_json()
2. Tier 2 -- Regex extraction: Strip code fences, extract JSON block, then validate
3. Tier 3 -- PARSE_ERROR: Return AgentDecision with signal=PARSE_ERROR

Usage:
    decision = parse_agent_decision(response.message.content)
"""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import ValidationError

from alphaswarm.inference.structured import json_object_candidates, strip_code_fences
from alphaswarm.types import AgentDecision, ErrorKind, SignalType

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
