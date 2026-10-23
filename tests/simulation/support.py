"""Shared constants and helpers for the tests/simulation/ modules."""

from __future__ import annotations

from alphaswarm.types import (
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MOCK_RUMOR = "ZZZT Holdings announces a breakthrough"


MOCK_SEED_EVENT = SeedEvent(
    raw_rumor=MOCK_RUMOR,
    entities=[
        SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
    ],
    overall_sentiment=0.6,
)


MOCK_PARSED_RESULT = ParsedSeedResult(seed_event=MOCK_SEED_EVENT, parse_tier=1)
