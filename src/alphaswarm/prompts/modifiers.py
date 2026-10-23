"""Prompt text and helpers for the per-cycle bracket modifier call (orchestrator)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from alphaswarm.security.sanitize import sanitize_entity_name
from alphaswarm.types import BracketType

if TYPE_CHECKING:
    from alphaswarm.types import SeedEvent


MODIFIER_CHAR_LIMIT = 150


def truncate_modifier(modifier: str) -> str:
    """Truncate modifier string at word boundary to MODIFIER_CHAR_LIMIT chars.

    If the modifier is already within the limit, returns it unchanged.
    Otherwise truncates at the last space before the limit.
    """
    if len(modifier) <= MODIFIER_CHAR_LIMIT:
        return modifier
    truncated = modifier[:MODIFIER_CHAR_LIMIT]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated  # Single very long word, hard truncate


def build_modifier_user_message(seed_event: SeedEvent) -> str:
    """Build the user message for modifier generation from SeedEvent (D-04).

    Includes both raw_rumor text and all extracted entities with their
    type, relevance, and sentiment metadata. Entity names are sanitized
    before interpolation (D-10, D-12).
    """
    entity_lines = []
    for e in seed_event.entities:
        safe_name = sanitize_entity_name(e.name)
        entity_lines.append(
            f"- {safe_name} (type: {e.type.value}, relevance: {e.relevance:.2f}, sentiment: {e.sentiment:+.2f})"
        )
    entities_block = "\n".join(entity_lines) if entity_lines else "(no entities extracted)"

    return f"SEED RUMOR:\n{seed_event.raw_rumor}\n\nEXTRACTED ENTITIES:\n{entities_block}"


BRACKET_MODIFIER_HINTS: Final[Mapping[BracketType, str]] = {
    BracketType.INSTITUTIONS: "Buy-side institutional portfolio managers",
    BracketType.SELL_SIDE: "Sell-side equity research analysts",
    BracketType.EVENT_DRIVEN: "Merger-arb / special-situations / catalyst funds",
    BracketType.QUANTS: "Quantitative analysts",
    BracketType.DEGENS: "High-risk retail speculators",
    BracketType.NARRATORS: "Financial media and FinTwit commentators",
    BracketType.ALGOS: "Algorithmic trading systems",
    BracketType.MACRO: "Global macro strategists",
    BracketType.SHORTS: "Forensic / activist short sellers",
    BracketType.ALLOCATORS: "Sovereign wealth and family-office allocators",
}
"""One line per bracket for the modifier prompt, in DEFAULT_BRACKETS order.

Keyed by BracketType instead of reading personas.DEFAULT_BRACKETS because personas
imports this package and import cycles are forbidden; tests/test_prompts.py pins
the order to DEFAULT_BRACKETS (docs/DECISIONS.md#adr-swarm-composition-v2).
"""


def render_modifier_generation_prompt(hints: Mapping[BracketType, str]) -> str:
    """The orchestrator system prompt asking for one modifier per bracket in ``hints``."""
    count = len(hints)
    bracket_lines = "".join(f"- {bracket.value}: {hint}\n" for bracket, hint in hints.items())
    example = ", ".join(f'"{bracket.value}": "..."' for bracket in hints)
    return (
        "You are a financial simulation configurator. Given a seed rumor"
        " and its extracted entities, generate one short personality modifier string"
        f" for each of the {count} market participant brackets.\n\n"
        "Each modifier should be 8-20 words describing a specialist persona tailored"
        " to the specific entities and themes in this rumor. The modifier completes"
        ' the sentence "You are a ..." so it should read naturally after that prefix.\n\n'
        f"The {count} brackets (use these exact keys):\n"
        f"{bracket_lines}\n"
        "Examples of good modifiers:\n"
        '- "quantitative analyst modeling EV supply chain disruption and margin compression"\n'
        '- "merger-arb specialist handicapping antitrust approval odds for this deal"\n'
        '- "tech-desk analyst defending a published price target on the acquirer"\n\n'
        "Respond with a JSON object mapping each bracket key to its modifier string."
        f" All {count} keys must be present.\n"
        f"Example: {{{example}}}"
    )


MODIFIER_GENERATION_PROMPT: Final = render_modifier_generation_prompt(BRACKET_MODIFIER_HINTS)
