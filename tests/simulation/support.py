"""Shared constants and helpers for the tests/simulation/ modules."""

from __future__ import annotations

from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketConfig,
    BracketType,
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MOCK_RUMOR = "NVIDIA announces breakthrough"


MOCK_SEED_EVENT = SeedEvent(
    raw_rumor=MOCK_RUMOR,
    entities=[
        SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
    ],
    overall_sentiment=0.6,
)


MOCK_PARSED_RESULT = ParsedSeedResult(seed_event=MOCK_SEED_EVENT, parse_tier=1)


# run_round1 never seeds: run_simulation passes the seeded cycle in.
_PRE_INJECTED = ("test-cycle-id", MOCK_PARSED_RESULT)


TEST_PERSONAS = [
    AgentPersona(
        id="quants_01",
        name="Quants 1",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 1",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="quants_02",
        name="Quants 2",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 2",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="degens_01",
        name="Degens 1",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 1",
        influence_weight_base=0.3,
    ),
    AgentPersona(
        id="degens_02",
        name="Degens 2",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 2",
        influence_weight_base=0.3,
    ),
]


TEST_BRACKETS = [
    BracketConfig(
        bracket_type=BracketType.QUANTS,
        display_name="Quants",
        count=2,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt_template="test",
        influence_weight_base=0.7,
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS,
        display_name="Degens",
        count=2,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt_template="test",
        influence_weight_base=0.3,
    ),
]


def _default_decisions(count: int) -> list[AgentDecision]:
    """Return a list of BUY AgentDecision for testing.

    Includes a non-empty rationale so peer-context builders emit real peer
    lines: _format_peer_context now returns "" when every selected peer has
    empty content (F-19), so empty-rationale decisions would yield no peer
    context at all.
    """
    return [AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="Bullish on the setup.")] * count


# ---------------------------------------------------------------------------
# Phase 07 Task 2 Tests: run_simulation
# ---------------------------------------------------------------------------


# Helper to build a Round1Result for mocking run_round1


def _mock_round1_result():
    from alphaswarm.simulation import Round1Result

    return Round1Result(
        cycle_id="test-cycle-id",
        parsed_result=MOCK_PARSED_RESULT,
        agent_decisions=[
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="momentum confirms")),
            ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.7, rationale="factors align")),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="fading the pump")),
            ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.5, rationale="exit liquidity")),
        ],
        decision_ids=[],  # round 1 is persisted inside the mocked run_round1
    )


# ---------------------------------------------------------------------------
# Phase 40 Plan 02 Task 2 Tests: run_simulation ContextPacket assembly
# ---------------------------------------------------------------------------


def _phase40_mock_parsed_result(entity_names: list[str]) -> ParsedSeedResult:
    """Build a ParsedSeedResult with the given entity names (all EntityType.COMPANY)."""
    return ParsedSeedResult(
        seed_event=SeedEvent(
            raw_rumor=MOCK_RUMOR,
            entities=[
                SeedEntity(
                    name=name,
                    type=EntityType.COMPANY,
                    relevance=0.95,
                    sentiment=0.6,
                )
                for name in entity_names
            ],
            overall_sentiment=0.6,
        ),
        parse_tier=1,
    )


# Per-round peer exposure keys for TEST_BRACKETS (quants, degens), rounds 2-3
# (docs/DECISIONS.md#adr-diverse-peer-context).
_EXPOSURE_KEYS_TEST_BRACKETS: frozenset[str] = frozenset(
    {
        f"r{n}_{kind}_{bracket}"
        for n in (2, 3)
        for kind in ("exposure", "readers_seeing")
        for bracket in ("quants", "degens")
    }
    | {"r2_distinct_peers_shown", "r3_distinct_peers_shown"}
)


# Control-holdout size and flip split, rounds 2-3 (docs/DECISIONS.md#adr-diverse-peer-context).
_CONTROL_KEYS: frozenset[str] = frozenset(
    f"r{n}_{kind}" for n in (2, 3) for kind in ("control_agents", "flips_control", "flips_treated")
)


# Peer parameters, experiment knobs and run provenance stamped on every cycle
# (docs/DECISIONS.md#adr-cycle-metrics).
_PROVENANCE_KEYS: frozenset[str] = frozenset(
    {
        "peer_selection_version",
        "peer_limit",
        "peer_min_brackets",
        "peer_bracket_cap",
        "peer_budget_chars",
        "peer_personal_boost",
        "peer_seed_source",
        "own_prior_memory",
        "control_fraction",
        "orchestrator_provider",
        "orchestrator_model",
        "worker_provider",
        "worker_model",
        "inference_mode",
        "git_sha",
        "git_dirty",
    }
)
