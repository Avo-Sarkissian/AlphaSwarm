"""Core type definitions for AlphaSwarm."""

from __future__ import annotations

import dataclasses
import math
from enum import StrEnum
from typing import Final, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator

# Lenient boundary normalisation (docs/DECISIONS.md#adr-structured-output):
# recoverable model output ("BUY", confidence 85) is normalised instead of
# being discarded as a parse error. Non-numbers pass through for pydantic.
_PERCENT_FLOOR: Final = 1.5


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):  # OverflowError: an int too large for a float
        return None
    return None if math.isnan(number) else number


def normalize_token(value: object) -> object:
    """Strip and lower-case strings ("  BUY " -> "buy"); other values unchanged."""
    return value.strip().lower() if isinstance(value, str) else value


def normalize_unit_interval(value: object) -> object:
    """Map a confidence-like number into [0, 1].

    Values in (1.5, 100] are read as percentages (85 -> 0.85); anything else is
    clamped. Non-numeric values, booleans and NaN are returned unchanged.
    """
    number = _as_number(value)
    if number is None:
        return value
    if _PERCENT_FLOOR < number <= 100.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def normalize_signed_unit(value: object) -> object:
    """Clamp a sentiment-like number to [-1, 1]; non-numbers unchanged."""
    number = _as_number(value)
    return value if number is None else max(-1.0, min(1.0, number))


# Engine-owned classification of a failed decision (docs/DECISIONS.md#adr-taskgroup-dispatch):
# "inference" = the model call raised, "parse" = tier-3 parse fallback,
# "truncated" = parse failure with finish_reason == "length" (the output cap cut the reply).
ErrorKind = Literal["inference", "parse", "truncated"]
# Governor states whose duration is reported in the cycle metrics. Defined here, not in
# telemetry.py, so governor -> telemetry -> inference -> governor never forms an import
# cycle (docs/DECISIONS.md#adr-inference-telemetry).
GovernorTelemetryState = Literal["throttled", "paused", "crisis"]


class BracketType(StrEnum):
    """The 10 market participant archetypes (v2 composition, 2026-06-10).

    Models the ACTIVE price-setting margin of the narrative ecosystem — who
    forms and propagates opinions about a rumor — not raw AUM. Passive/index
    capital and market makers are deliberately excluded: the former never
    reacts to rumors by definition, the latter's honest reaction ("vol up,
    quote both sides") doesn't fit a buy/sell/hold ontology.

    v1→v2 mapping: SUITS split into INSTITUTIONS + SELL_SIDE; SOVEREIGNS and
    WHALES merged into ALLOCATORS; AGENTS renamed ALGOS; DOOM_POSTERS folded
    into SHORTS as a personality modifier; INSIDERS folded into EVENT_DRIVEN
    modifiers (options-flow / channel-check archetypes); POLICY_WONKS folded
    into EVENT_DRIVEN (antitrust handicapper) + MACRO (fiscal-policy watcher)
    modifiers; NARRATORS added (media/FinTwit — the cascade's transmission
    channel, high reach with no capital).
    """

    INSTITUTIONS = "institutions"
    SELL_SIDE = "sell_side"
    EVENT_DRIVEN = "event_driven"
    QUANTS = "quants"
    DEGENS = "degens"
    NARRATORS = "narrators"
    ALGOS = "algos"
    MACRO = "macro"
    SHORTS = "shorts"
    ALLOCATORS = "allocators"


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
    # Length of the bracket-shared start of system_prompt (rules, template, cycle
    # focus); the rest is this agent's own text (docs/DECISIONS.md#adr-prefix-reuse).
    shared_prompt_chars: int = Field(default=0, ge=0)


class WorkerPersonaConfig(TypedDict):
    """Lightweight runtime persona config for hot-path agent inference.

    Derived from the frozen AgentPersona at dispatch time via
    persona_to_worker_config(). A TypedDict (not a pydantic model) keeps the
    100-call inference hot path cheap.
    """

    agent_id: str
    bracket: str  # BracketType.value string
    influence_weight: float
    temperature: float
    system_prompt: str
    risk_profile: float  # AgentPersona.risk_profile; unused by the prompt (docs/DECISIONS.md#adr-swarm-composition-v2)
    shared_prompt_chars: NotRequired[int]  # see AgentPersona.shared_prompt_chars


class SignalType(StrEnum):
    """Trading signal types."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    PARSE_ERROR = "parse_error"


class FlipType(StrEnum):
    """Signal transition types between consecutive rounds (D-06)."""

    NONE = "none"
    BUY_TO_SELL = "buy_to_sell"
    SELL_TO_BUY = "sell_to_buy"
    BUY_TO_HOLD = "buy_to_hold"
    HOLD_TO_BUY = "hold_to_buy"
    SELL_TO_HOLD = "sell_to_hold"
    HOLD_TO_SELL = "hold_to_sell"


class EntityType(StrEnum):
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

    @field_validator("type", mode="before")
    @classmethod
    def _normalise_type(cls, value: object) -> object:
        return normalize_token(value)

    @field_validator("relevance", mode="before")
    @classmethod
    def _normalise_relevance(cls, value: object) -> object:
        return normalize_unit_interval(value)

    @field_validator("sentiment", mode="before")
    @classmethod
    def _normalise_sentiment(cls, value: object) -> object:
        return normalize_signed_unit(value)


class SeedEvent(BaseModel, frozen=True):
    """Structured seed rumor with extracted entities and aggregate sentiment."""

    raw_rumor: str
    entities: list[SeedEntity]
    overall_sentiment: float = Field(ge=-1.0, le=1.0)

    @field_validator("overall_sentiment", mode="before")
    @classmethod
    def _normalise_overall_sentiment(cls, value: object) -> object:
        return normalize_signed_unit(value)


@dataclasses.dataclass(frozen=True)
class ParsedSeedResult:
    """Result of seed extraction (seed.inject_seed) with parse-tier observability.

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
    # Never part of the LLM-facing schema; set by the parser or the dispatcher.
    error_kind: ErrorKind | None = None
    # Engine-owned like error_kind (docs/DECISIONS.md#adr-structured-output): 1 direct
    # JSON, 2 extracted, 3 parser fallback; None when the parser did not produce the decision.
    parse_tier: Literal[1, 2, 3] | None = None

    @field_validator("signal", mode="before")
    @classmethod
    def _normalise_signal(cls, value: object) -> object:
        return normalize_token(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalise_confidence(cls, value: object) -> object:
        return normalize_unit_interval(value)

    @field_validator("sentiment", mode="before")
    @classmethod
    def _normalise_sentiment(cls, value: object) -> object:
        return normalize_signed_unit(value)


class SimulationPhase(StrEnum):
    """Lifecycle phases of a simulation run."""

    IDLE = "idle"
    SEEDING = "seeding"
    ROUND_1 = "round_1"
    ROUND_2 = "round_2"
    ROUND_3 = "round_3"
    FINALIZING = "finalizing"  # after the last round: the metrics and status write
    COMPLETE = "complete"
    REPLAY = "replay"
