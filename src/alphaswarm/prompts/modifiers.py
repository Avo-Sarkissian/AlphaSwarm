"""Prompt text and helpers for the per-cycle bracket modifier call (orchestrator)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaswarm.security.sanitize import sanitize_entity_name

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


# ---------------------------------------------------------------------------
# Modifier generation prompt and helpers (Phase 13, D-04, D-05, D-06)
# ---------------------------------------------------------------------------

MODIFIER_GENERATION_PROMPT = (
    "You are a financial simulation configurator. Given a seed rumor"
    " and its extracted entities, generate one short personality modifier string"
    " for each of the 10 market participant brackets.\n\n"
    "Each modifier should be 8-20 words describing a specialist persona tailored"
    " to the specific entities and themes in this rumor. The modifier completes"
    ' the sentence "You are a ..." so it should read naturally after that prefix.\n\n'
    "The 10 brackets (use these exact keys):\n"
    "- institutions: Buy-side institutional portfolio managers\n"
    "- sell_side: Sell-side equity research analysts\n"
    "- event_driven: Merger-arb / special-situations / catalyst funds\n"
    "- quants: Quantitative analysts\n"
    "- degens: High-risk retail speculators\n"
    "- narrators: Financial media and FinTwit commentators\n"
    "- algos: Algorithmic trading systems\n"
    "- macro: Global macro strategists\n"
    "- shorts: Forensic / activist short sellers\n"
    "- allocators: Sovereign wealth and family-office allocators\n\n"
    "Examples of good modifiers:\n"
    '- "quantitative analyst modeling EV supply chain disruption and margin compression"\n'
    '- "merger-arb specialist handicapping antitrust approval odds for this deal"\n'
    '- "tech-desk analyst defending a published price target on the acquirer"\n\n'
    "Respond with a JSON object mapping each bracket key to its modifier string."
    " All 10 keys must be present.\n"
    'Example: {"institutions": "...", "sell_side": "...",'
    ' "event_driven": "...", "quants": "...", "degens": "...",'
    ' "narrators": "...", "algos": "...", "macro": "...",'
    ' "shorts": "...", "allocators": "..."}'
)


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
