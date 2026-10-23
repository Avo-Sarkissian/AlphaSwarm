"""Hypothesis properties: decision parsing and flip classification.

The select_diverse_peers properties (self and PARSE_ERROR exclusion, no duplicates,
limit, bracket cap and floor, determinism) live in tests/test_peer_selection.py.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from alphaswarm.episodes import compute_flip_type
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.types import AgentDecision, FlipType, SignalType

PERSONAS = generate_personas(list(DEFAULT_BRACKETS))
AGENT_IDS = [p.id for p in PERSONAS]

_rationales = st.text(alphabet=st.characters(blacklist_characters="`", blacklist_categories=("Cs",)), max_size=200)
# error_kind is engine-owned: the parser sets "parse" for a parse-error signal and None
# otherwise (docs/DECISIONS.md#adr-structured-output), so only consistent decisions round-trip.
decisions = st.builds(
    AgentDecision,
    signal=st.sampled_from(list(SignalType)),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    sentiment=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False),
    rationale=_rationales,
    cited_agents=st.lists(st.sampled_from(AGENT_IDS), max_size=3),
).map(lambda d: d.model_copy(update={"error_kind": "parse" if d.signal is SignalType.PARSE_ERROR else None}))


@settings(max_examples=200, deadline=None)
@given(raw=st.text(max_size=500))
def test_parse_agent_decision_never_raises(raw: str) -> None:
    decision = parse_agent_decision(raw)
    assert isinstance(decision, AgentDecision)
    if "{" not in raw:
        assert decision.signal is SignalType.PARSE_ERROR
        assert decision.confidence == 0.0


@settings(max_examples=200, deadline=None)
@given(decision=decisions)
def test_parse_agent_decision_round_trips_plain_and_fenced_json(decision: AgentDecision) -> None:
    payload = decision.model_dump_json()
    assert parse_agent_decision(payload) == decision
    assert parse_agent_decision(f"Sure.\n```json\n{payload}\n```\nDone.") == decision


@settings(max_examples=100, deadline=None)
@given(
    prev=st.one_of(st.none(), st.sampled_from(list(SignalType))),
    curr=st.sampled_from(list(SignalType)),
)
def test_compute_flip_type_matches_its_definition(prev: SignalType | None, curr: SignalType) -> None:
    flip = compute_flip_type(prev, curr)
    if prev is None or SignalType.PARSE_ERROR in (prev, curr) or prev == curr:
        assert flip is FlipType.NONE
    else:
        assert flip.value == f"{prev.value}_to_{curr.value}"
