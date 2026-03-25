"""Pydantic settings hierarchy and bracket/persona definitions for AlphaSwarm."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from alphaswarm.types import AgentPersona, BracketConfig, BracketType

if TYPE_CHECKING:
    from alphaswarm.worker import WorkerPersonaConfig


# ---------------------------------------------------------------------------
# Nested settings models
# ---------------------------------------------------------------------------


class OllamaSettings(BaseModel):
    """Ollama inference server configuration."""

    orchestrator_model: str = "qwen3.5:32b"
    worker_model: str = "qwen3.5:7b"
    num_parallel: int = Field(default=16, ge=1, le=32)
    max_loaded_models: int = Field(default=2, ge=1, le=4)
    base_url: str = "http://localhost:11434"
    orchestrator_model_alias: str = "alphaswarm-orchestrator"
    worker_model_alias: str = "alphaswarm-worker"


class Neo4jSettings(BaseModel):
    """Neo4j graph database connection configuration."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "alphaswarm"
    database: str = "neo4j"


class GovernorSettings(BaseModel):
    """Resource governor thresholds for memory-aware throttling."""

    baseline_parallel: int = Field(default=8, ge=1, le=32)
    max_parallel: int = Field(default=16, ge=1, le=32)
    memory_throttle_percent: float = Field(default=80.0, ge=50.0, le=95.0)
    memory_pause_percent: float = Field(default=90.0, ge=60.0, le=99.0)
    check_interval_seconds: float = Field(default=2.0, ge=0.5, le=10.0)

    # Phase 3: Dynamic governor fields (D-01, D-02, D-04, D-05, D-07, D-14)
    scale_up_threshold_percent: float = Field(default=60.0, ge=30.0, le=80.0)
    scale_up_consecutive_checks: int = Field(default=3, ge=1, le=10)
    crisis_timeout_seconds: float = Field(default=300.0, ge=30.0, le=600.0)
    slot_adjustment_step: int = Field(default=2, ge=1, le=4)
    batch_failure_threshold_percent: float = Field(default=20.0, ge=5.0, le=50.0)
    jitter_min_seconds: float = Field(default=0.5, ge=0.0, le=2.0)
    jitter_max_seconds: float = Field(default=1.5, ge=0.5, le=5.0)


# ---------------------------------------------------------------------------
# Root application settings
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    """Root configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ALPHASWARM_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "AlphaSwarm"
    debug: bool = False
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    ollama: OllamaSettings = OllamaSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    governor: GovernorSettings = GovernorSettings()


# ---------------------------------------------------------------------------
# Default bracket definitions
# ---------------------------------------------------------------------------

DEFAULT_BRACKETS: list[BracketConfig] = [
    BracketConfig(
        bracket_type=BracketType.QUANTS,
        display_name="Quants",
        count=10,
        risk_profile=0.4,
        temperature=0.3,
        influence_weight_base=0.7,
        system_prompt_template=(
            "You are a quantitative analyst. You rely on statistical models, "
            "historical data, and mathematical signals to form market opinions. "
            "Emotion is noise; only the numbers matter."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS,
        display_name="Degens",
        count=20,
        risk_profile=0.95,
        temperature=1.2,
        influence_weight_base=0.3,
        system_prompt_template=(
            "You are a high-risk speculator driven by momentum and hype. "
            "You chase volatile plays, leverage heavily, and react fast to rumors. "
            "FOMO is your fuel; risk management is for the timid."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.SOVEREIGNS,
        display_name="Sovereigns",
        count=10,
        risk_profile=0.15,
        temperature=0.4,
        influence_weight_base=0.9,
        system_prompt_template=(
            "You represent a sovereign wealth fund or central bank. "
            "Your mandate is capital preservation and long-term stability. "
            "You move slowly, deliberately, and your positions carry enormous weight."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.MACRO,
        display_name="Macro",
        count=10,
        risk_profile=0.35,
        temperature=0.5,
        influence_weight_base=0.6,
        system_prompt_template=(
            "You are a global macro strategist. You analyze interest rates, "
            "geopolitical events, and cross-asset correlations to form theses. "
            "Individual stocks matter less than systemic trends."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.SUITS,
        display_name="Suits",
        count=10,
        risk_profile=0.2,
        temperature=0.3,
        influence_weight_base=0.8,
        system_prompt_template=(
            "You are a traditional institutional investor at a major bank or fund. "
            "You follow established frameworks, consensus views, and regulatory guidance. "
            "Reputation risk matters as much as return."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.INSIDERS,
        display_name="Insiders",
        count=10,
        risk_profile=0.5,
        temperature=0.6,
        influence_weight_base=0.75,
        system_prompt_template=(
            "You have privileged access to non-public information and industry networks. "
            "You read between the lines of earnings calls and regulatory filings. "
            "Your edge is informational asymmetry."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.AGENTS,
        display_name="Agents",
        count=15,
        risk_profile=0.6,
        temperature=0.1,
        influence_weight_base=0.5,
        system_prompt_template=(
            "You are an algorithmic trading agent executing systematic strategies. "
            "You process signals with minimal latency and zero emotional bias. "
            "Your decisions are deterministic given your inputs."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.DOOM_POSTERS,
        display_name="Doom-Posters",
        count=5,
        risk_profile=0.8,
        temperature=1.0,
        influence_weight_base=0.4,
        system_prompt_template=(
            "You are a perma-bear and crisis prophet. Every signal confirms imminent collapse. "
            "You amplify negative narratives and dismiss bullish evidence as manipulation. "
            "The crash is always around the corner."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.POLICY_WONKS,
        display_name="Policy Wonks",
        count=5,
        risk_profile=0.25,
        temperature=0.4,
        influence_weight_base=0.65,
        system_prompt_template=(
            "You analyze markets through the lens of regulation, fiscal policy, and legislation. "
            "Fed speeches, congressional hearings, and executive orders drive your outlook. "
            "Policy is the ultimate market mover."
        ),  # TODO: Refine for Phase 5
    ),
    BracketConfig(
        bracket_type=BracketType.WHALES,
        display_name="Whales",
        count=5,
        risk_profile=0.3,
        temperature=0.5,
        influence_weight_base=0.85,
        system_prompt_template=(
            "You are a high-net-worth individual or family office with massive capital. "
            "Your trades move markets. You think in decades, not quarters. "
            "Access to the best advisors shapes your measured, contrarian approach."
        ),  # TODO: Refine for Phase 5
    ),
]


def load_bracket_configs() -> list[BracketConfig]:
    """Return the default bracket configurations.

    Wrapper for future extensibility (e.g., loading from file or database).
    """
    return list(DEFAULT_BRACKETS)


def validate_bracket_counts(brackets: list[BracketConfig]) -> None:
    """Raise ValueError if bracket counts do not sum to 100."""
    total = sum(b.count for b in brackets)
    if total != 100:
        msg = f"Bracket counts must sum to 100, got {total}"
        raise ValueError(msg)


def generate_personas(brackets: list[BracketConfig]) -> list[AgentPersona]:
    """Generate all agent personas from bracket definitions.

    Returns a flat list of 100 AgentPersona instances with unique IDs.
    """
    validate_bracket_counts(brackets)
    personas: list[AgentPersona] = []
    for bracket in brackets:
        for i in range(1, bracket.count + 1):
            agent_id = f"{bracket.bracket_type.value}_{i:02d}"
            agent_name = f"{bracket.display_name} {i}"
            system_prompt = (
                f"[{agent_name} | {bracket.display_name} bracket]\n"
                f"{bracket.system_prompt_template}"
            )
            personas.append(
                AgentPersona(
                    id=agent_id,
                    name=agent_name,
                    bracket=bracket.bracket_type,
                    risk_profile=bracket.risk_profile,
                    temperature=bracket.temperature,
                    system_prompt=system_prompt,
                    influence_weight_base=bracket.influence_weight_base,
                )
            )
    return personas


def persona_to_worker_config(persona: AgentPersona) -> WorkerPersonaConfig:
    """Convert a frozen AgentPersona to a lightweight WorkerPersonaConfig TypedDict.

    This is the defined conversion boundary between the Pydantic source-of-truth
    model and the hot-path TypedDict used by agent_worker.
    Addresses review concern: WorkerPersonaConfig conversion boundary.
    """
    from alphaswarm.worker import WorkerPersonaConfig

    return WorkerPersonaConfig(
        agent_id=persona.id,
        bracket=persona.bracket.value,
        influence_weight=persona.influence_weight_base,
        temperature=persona.temperature,
        system_prompt=persona.system_prompt,
        risk_profile=str(persona.risk_profile),
    )
