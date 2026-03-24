"""Structured output parsing for LLM responses.

Implements the INFRA-08 3-tier fallback:
1. Tier 1 -- Native JSON mode: Direct Pydantic model_validate_json()
2. Tier 2 -- Regex extraction: Strip code fences, extract JSON block, then validate
3. Tier 3 -- PARSE_ERROR: Return AgentDecision with signal=PARSE_ERROR

Usage:
    decision = parse_agent_decision(response.message.content)
"""

from __future__ import annotations

import re

import structlog
from pydantic import ValidationError

from alphaswarm.types import AgentDecision, SignalType

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
