"""ISOL-02: Frozen pydantic types for the ingestion->swarm seam.

All types use pydantic v2 `ConfigDict(frozen=True, extra="forbid")` —
runtime construction rejects unknown keys, static mypy rejects attribute drift.
Zero holdings fields by design; see importlinter contract (Plan 04) for the
complementary static enforcement.

REVIEW HIGH (2026-04-18, cross-AI review):
  - All collection fields are tuple[...] — frozen does NOT prevent list mutation
    (`packet.market.append(...)` would work on a frozen pydantic model with
    a list field; .append is the LIST's method, not the model's).
  - `fundamentals` is a nested frozen `Fundamentals` sub-model — NOT `dict[str, float]`.
    A dict field is mutable even when its enclosing model is frozen
    (`packet.market[0].fundamentals["pe_ratio"] = 999` would succeed).

REVIEW MEDIUM: MarketSlice.price is Decimal (not float) — financial precision
guard against binary-float rounding. `volume` stays int (share counts are exact).
StalenessState is a typed Literal alias, not unconstrained str.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StalenessState = Literal["fresh", "stale", "fetch_failed"]


class Fundamentals(BaseModel):
    """Frozen named-fields sub-model replacing dict[str, float] for fundamentals.

    REVIEW HIGH: a dict on a frozen model is still mutable via .update()/.pop()/
    subscript assignment. Named Decimal fields on a frozen BaseModel produce a
    truly immutable value graph.

    All fields Decimal for financial precision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pe_ratio: Decimal | None = None
    eps: Decimal | None = None
    market_cap: Decimal | None = None


class MarketSlice(BaseModel):
    """Per-ticker market data slice produced by a MarketDataProvider.

    REVIEW MEDIUM: price is Decimal for financial precision (binary float
    rounding on money is a known pitfall). volume stays int — share counts
    are exact integers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    price: Decimal | None = None
    volume: int | None = None
    fundamentals: Fundamentals | None = None
    fetched_at: datetime
    source: str
    staleness: StalenessState = "fresh"


class NewsSlice(BaseModel):
    """Per-entity news slice produced by a NewsProvider.

    REVIEW HIGH: headlines is tuple[str, ...] — frozen doesn't freeze list contents.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: str
    headlines: tuple[str, ...] = Field(default_factory=tuple)
    fetched_at: datetime
    source: str
    staleness: StalenessState = "fresh"


class ContextPacket(BaseModel):
    """Frozen packet handed from ingestion to the swarm.

    Zero holdings fields by construction. Adding any field here requires editing
    this class definition — which is the intended drift barrier.

    REVIEW HIGH: entities/market/news are ALL tuple[...] — a list field would
    let callers mutate the packet in place after construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    as_of: datetime
    entities: tuple[str, ...]
    market: tuple[MarketSlice, ...] = Field(default_factory=tuple)
    news: tuple[NewsSlice, ...] = Field(default_factory=tuple)
