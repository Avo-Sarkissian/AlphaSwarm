"""Ingestion subpackage — swarm-safe types and provider Protocols.

Types (ContextPacket, MarketSlice, NewsSlice, Fundamentals) have ZERO
holdings-shaped fields by construction (ISOL-02) and reject unknown keys at
runtime via extra='forbid'. Collection fields use tuple[...] (REVIEW HIGH).
Provider Protocols live in providers.py (Plan 02).
"""

from alphaswarm.ingestion.types import (
    ContextPacket,
    Fundamentals,
    MarketSlice,
    NewsSlice,
    StalenessState,
)

__all__ = [
    "ContextPacket",
    "Fundamentals",
    "MarketSlice",
    "NewsSlice",
    "StalenessState",
]
