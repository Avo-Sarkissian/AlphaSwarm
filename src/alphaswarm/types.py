"""Core type definitions for AlphaSwarm."""

from __future__ import annotations

import dataclasses
from enum import Enum

from pydantic import BaseModel, Field


class BracketType(str, Enum):
    """The 10 market participant archetypes."""

    QUANTS = "quants"
    DEGENS = "degens"
    SOVEREIGNS = "sovereigns"
    MACRO = "macro"
    SUITS = "suits"
    INSIDERS = "insiders"
    AGENTS = "agents"
    DOOM_POSTERS = "doom_posters"
    POLICY_WONKS = "policy_wonks"
    WHALES = "whales"


class BracketConfig(BaseModel, frozen=True):
    """Configuration for a single bracket archetype."""

    bracket_type: BracketType
    display_name: str
    count: int = Field(ge=1, le=100)
    risk_profile: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.0, le=2.0)
    system_prompt_template: str
    influence_weight_base: float = Field(ge=0.0, le=1.0)


class AgentPersona(BaseModel, frozen=True):
    """A single agent persona instantiated from a bracket."""

    id: str
    name: str
    bracket: BracketType
    risk_profile: float
    temperature: float
    system_prompt: str
    influence_weight_base: float


class SignalType(str, Enum):
    """Trading signal types."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    PARSE_ERROR = "parse_error"


class FlipType(str, Enum):
    """Signal transition types between consecutive rounds (D-06)."""

    NONE = "none"
    BUY_TO_SELL = "buy_to_sell"
    SELL_TO_BUY = "sell_to_buy"
    BUY_TO_HOLD = "buy_to_hold"
    HOLD_TO_BUY = "hold_to_buy"
    SELL_TO_HOLD = "sell_to_hold"
    HOLD_TO_SELL = "hold_to_sell"


class EntityType(str, Enum):
    """Named entity types extracted from seed rumors."""

    COMPANY = "company"
    SECTOR = "sector"
    PERSON = "person"


class SeedEntity(BaseModel, frozen=True):
    """A single named entity extracted from a seed rumor."""

    name: str
    type: EntityType
    relevance: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0)


class SeedEvent(BaseModel, frozen=True):
    """Structured seed rumor with extracted entities and aggregate sentiment."""

    raw_rumor: str
    entities: list[SeedEntity]
    overall_sentiment: float = Field(ge=-1.0, le=1.0)


class MarketDataSnapshot(BaseModel, frozen=True):
    """Market data snapshot for a single ticker. Per Phase 17 D-03."""

    symbol: str
    company_name: str = ""
    # Price history: 90-day daily OHLCV (D-01)
    price_history: list[dict[str, float | int | str]] = Field(default_factory=list)
    # Financial fundamentals (D-02)
    pe_ratio: float | None = None
    market_cap: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    eps_trailing: float | None = None
    revenue_ttm: float | None = None
    gross_margin_pct: float | None = None
    debt_to_equity: float | None = None
    earnings_surprise_pct: float | None = None
    next_earnings_date: str | None = None
    # Computed summary stats for quick access
    last_close: float | None = None
    price_change_30d_pct: float | None = None
    price_change_90d_pct: float | None = None
    avg_volume_30d: float | None = None
    # Reserved for Phase 18 (D-04: news deferred, DATA-03 compliance in Phase 18)
    headlines: list[str] = Field(default_factory=list)
    # Degraded flag (D-15: True when both yfinance and AV fail)
    is_degraded: bool = False


class ExtractedTicker(BaseModel, frozen=True):
    """A ticker symbol extracted from a seed rumor for market data fetching (Phase 17)."""

    symbol: str
    company_name: str
    relevance: float = Field(ge=0.0, le=1.0)


@dataclasses.dataclass(frozen=True)
class ParsedSeedResult:
    """Result of parse_seed_event() with parse-tier observability.

    Addresses review concern: Tier-3 fallback returning empty SeedEvent was
    indistinguishable from genuine "no entities found". parse_tier makes the
    distinction observable.

    parse_tier values:
      1 = Direct JSON parse succeeded
      2 = Code-fence strip / regex extraction succeeded
      3 = All tiers failed, fallback SeedEvent returned
    """

    seed_event: SeedEvent
    parse_tier: int


@dataclasses.dataclass(frozen=True)
class ParsedModifiersResult:
    """Result of modifier generation with parse-tier observability (D-09).

    parse_tier values:
      1 = Direct JSON parse succeeded
      2 = Code-fence strip / regex extraction succeeded
      3 = All tiers failed, fallback to static BRACKET_MODIFIERS
    """

    modifiers: dict[BracketType, str]
    parse_tier: int


class AgentDecision(BaseModel, frozen=True):
    """Structured decision output from an agent inference call."""

    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    rationale: str = ""
    cited_agents: list[str] = Field(default_factory=list)


class SimulationPhase(str, Enum):
    """Lifecycle phases of a simulation run."""

    IDLE = "idle"
    SEEDING = "seeding"
    ROUND_1 = "round_1"
    ROUND_2 = "round_2"
    ROUND_3 = "round_3"
    COMPLETE = "complete"
