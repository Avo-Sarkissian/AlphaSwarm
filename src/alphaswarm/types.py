"""Core type definitions for AlphaSwarm."""

from __future__ import annotations

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


class SimulationPhase(str, Enum):
    """Lifecycle phases of a simulation run."""

    IDLE = "idle"
    SEEDING = "seeding"
    ROUND_1 = "round_1"
    ROUND_2 = "round_2"
    ROUND_3 = "round_3"
    COMPLETE = "complete"
