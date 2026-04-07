"""Integration tests for sub-wave dispatch and enrichment wiring in simulation.py (Phase 18, Plan 03).

Tests verify:
- _group_personas_by_slice groups 10 brackets into 3 groups correctly
- _dispatch_enriched_sub_waves with empty snapshots dispatches single wave with bare rumor
- _dispatch_enriched_sub_waves with snapshots dispatches 3 sub-waves (bracket groups)
- Sub-wave results merged in original persona order (not insertion order)
- Peer contexts correctly sliced per sub-wave group
- Bracket-specific content (Quants see close=, Suits see PE=)
- Decision count matches persona count (positional invariant)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketType,
    MarketDataSnapshot,
    SignalType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RUMOR = "Apple might acquire a chip maker"


def _make_persona(agent_id: str, bracket: BracketType) -> AgentPersona:
    """Build a minimal AgentPersona for testing."""
    return AgentPersona(
        id=agent_id,
        name=agent_id.replace("_", " ").title(),
        bracket=bracket,
        risk_profile=0.5,
        temperature=0.7,
        system_prompt=f"test prompt for {agent_id}",
        influence_weight_base=0.5,
    )


# 6 personas covering all 3 bracket groups (2 per group)
TEST_PERSONAS = [
    _make_persona("quant_01", BracketType.QUANTS),      # Technicals
    _make_persona("quant_02", BracketType.QUANTS),      # Technicals
    _make_persona("suit_01", BracketType.SUITS),        # Fundamentals
    _make_persona("suit_02", BracketType.SUITS),        # Fundamentals
    _make_persona("insider_01", BracketType.INSIDERS),  # Earnings/Insider
    _make_persona("insider_02", BracketType.INSIDERS),  # Earnings/Insider
]

# Interleaved order for merge-order testing
INTERLEAVED_PERSONAS = [
    _make_persona("quant_01", BracketType.QUANTS),
    _make_persona("suit_01", BracketType.SUITS),
    _make_persona("insider_01", BracketType.INSIDERS),
    _make_persona("quant_02", BracketType.QUANTS),
    _make_persona("suit_02", BracketType.SUITS),
    _make_persona("insider_02", BracketType.INSIDERS),
]

AAPL_SNAP = MarketDataSnapshot(
    symbol="AAPL",
    company_name="Apple Inc.",
    last_close=182.50,
    price_change_30d_pct=4.2,
    price_change_90d_pct=8.1,
    avg_volume_30d=48_200_000,
    fifty_two_week_high=199.0,
    fifty_two_week_low=142.0,
    pe_ratio=28.5,
    market_cap=3_000_000_000_000,
    revenue_ttm=400_000_000_000,
    gross_margin_pct=45.0,
    debt_to_equity=1.5,
    earnings_surprise_pct=5.2,
    next_earnings_date="2025-07-15",
    eps_trailing=6.50,
)

MARKET_SNAPSHOTS: dict[str, MarketDataSnapshot] = {"AAPL": AAPL_SNAP}


def _make_decision(signal: SignalType, agent_id: str = "agent") -> AgentDecision:
    """Build a minimal AgentDecision."""
    return AgentDecision(
        signal=signal,
        confidence=0.8,
        sentiment=0.5,
        rationale=f"Test rationale for {agent_id}",
    )


# ---------------------------------------------------------------------------
# _group_personas_by_slice tests
# ---------------------------------------------------------------------------


def test_group_personas_by_slice_three_groups() -> None:
    """6 personas (2 per group) should produce 3 groups."""
    from alphaswarm.simulation import _group_personas_by_slice

    groups = _group_personas_by_slice(TEST_PERSONAS)
    assert len(groups) == 3

    # Collect all brackets from each group
    all_brackets = set()
    for group_personas, rep_bracket in groups:
        assert len(group_personas) == 2
        all_brackets.add(rep_bracket)

    # All 3 representative brackets present
    assert BracketType.QUANTS in all_brackets
    assert BracketType.SUITS in all_brackets
    assert BracketType.INSIDERS in all_brackets


# ---------------------------------------------------------------------------
# _dispatch_enriched_sub_waves tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_no_snapshots_single_wave() -> None:
    """Empty market_snapshots should dispatch ONE wave with bare rumor."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    fake_decisions = [_make_decision(SignalType.BUY, p.id) for p in TEST_PERSONAS]

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = fake_decisions

        result = await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots={},
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    # dispatch_wave called exactly ONCE (single wave, no sub-waving)
    assert mock_dispatch.call_count == 1
    # With bare rumor (not enriched)
    call_kwargs = mock_dispatch.call_args
    assert call_kwargs.kwargs.get("user_message", call_kwargs.args[4] if len(call_kwargs.args) > 4 else None) is not None
    # Check user_message is bare rumor
    if "user_message" in mock_dispatch.call_args.kwargs:
        assert mock_dispatch.call_args.kwargs["user_message"] == RUMOR
    # Returns correct count
    assert len(result) == len(TEST_PERSONAS)


@pytest.mark.asyncio
async def test_dispatch_with_snapshots_three_waves() -> None:
    """Populated market_snapshots should dispatch 3 sub-waves (one per bracket group)."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    # Build per-group decision lists
    quant_decisions = [_make_decision(SignalType.BUY, "quant_01"), _make_decision(SignalType.BUY, "quant_02")]
    suit_decisions = [_make_decision(SignalType.SELL, "suit_01"), _make_decision(SignalType.SELL, "suit_02")]
    insider_decisions = [_make_decision(SignalType.HOLD, "insider_01"), _make_decision(SignalType.HOLD, "insider_02")]

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        personas_arg = kwargs["personas"]
        count = len(personas_arg)
        call_count += 1
        # Return decisions matching sub-wave persona count
        if call_count == 1:
            return quant_decisions[:count]
        elif call_count == 2:
            return suit_decisions[:count]
        else:
            return insider_decisions[:count]

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        result = await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    # 3 sub-waves dispatched
    assert call_count == 3
    # Total decisions = 6
    assert len(result) == 6


@pytest.mark.asyncio
async def test_dispatch_merge_order() -> None:
    """Sub-wave results are merged in original persona order, not sub-wave insertion order."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    # Use interleaved personas: [quant, suit, insider, quant, suit, insider]
    # Each group gets a distinct signal: quant=BUY, suit=SELL, insider=HOLD

    call_idx = 0

    async def _side_effect(**kwargs):
        nonlocal call_idx
        personas_arg = kwargs["personas"]
        call_idx += 1
        decisions = []
        for p in personas_arg:
            bracket = p["bracket"]
            if bracket == "quants":
                decisions.append(_make_decision(SignalType.BUY, p["agent_id"]))
            elif bracket == "suits":
                decisions.append(_make_decision(SignalType.SELL, p["agent_id"]))
            else:
                decisions.append(_make_decision(SignalType.HOLD, p["agent_id"]))
        return decisions

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        result = await _dispatch_enriched_sub_waves(
            personas=INTERLEAVED_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    # Verify results are in ORIGINAL persona order (interleaved), not grouped
    expected_signals = [
        SignalType.BUY,   # quant_01
        SignalType.SELL,  # suit_01
        SignalType.HOLD,  # insider_01
        SignalType.BUY,   # quant_02
        SignalType.SELL,  # suit_02
        SignalType.HOLD,  # insider_02
    ]
    actual_signals = [d.signal for d in result]
    assert actual_signals == expected_signals


@pytest.mark.asyncio
async def test_dispatch_peer_contexts_sliced() -> None:
    """peer_contexts_by_id dict is correctly sliced per sub-wave group."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    # Per-agent peer contexts
    peer_contexts_by_id = {
        "quant_01": "quant_01 peers",
        "quant_02": "quant_02 peers",
        "suit_01": "suit_01 peers",
        "suit_02": "suit_02 peers",
        "insider_01": "insider_01 peers",
        "insider_02": "insider_02 peers",
    }

    captured_calls: list[dict] = []

    async def _side_effect(**kwargs):
        captured_calls.append(kwargs)
        personas_arg = kwargs["personas"]
        return [_make_decision(SignalType.BUY, p["agent_id"]) for p in personas_arg]

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
            peer_contexts_by_id=peer_contexts_by_id,
        )

    # 3 sub-waves
    assert len(captured_calls) == 3

    # Each sub-wave should receive only peer contexts for its group
    for call in captured_calls:
        personas_in_call = call["personas"]
        peer_ctxs = call.get("peer_contexts")
        assert peer_ctxs is not None
        assert len(peer_ctxs) == len(personas_in_call)
        for p, ctx in zip(personas_in_call, peer_ctxs):
            assert ctx == peer_contexts_by_id[p["agent_id"]]


@pytest.mark.asyncio
async def test_quant_message_has_close_field() -> None:
    """Quants sub-wave user_message contains 'close=' substring."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    captured_messages: list[str] = []

    async def _side_effect(**kwargs):
        captured_messages.append(kwargs.get("user_message", ""))
        personas_arg = kwargs["personas"]
        return [_make_decision(SignalType.BUY, p["agent_id"]) for p in personas_arg]

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    # The Quants sub-wave message should contain "close="
    quant_message = captured_messages[0]  # Technicals group dispatched first
    assert "close=" in quant_message


@pytest.mark.asyncio
async def test_suit_message_has_pe_field() -> None:
    """Suits sub-wave user_message contains 'PE=' substring."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    captured_messages: list[str] = []

    async def _side_effect(**kwargs):
        captured_messages.append(kwargs.get("user_message", ""))
        personas_arg = kwargs["personas"]
        return [_make_decision(SignalType.BUY, p["agent_id"]) for p in personas_arg]

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    # The Suits sub-wave message (second group) should contain "PE="
    suit_message = captured_messages[1]  # Fundamentals group dispatched second
    assert "PE=" in suit_message


@pytest.mark.asyncio
async def test_decision_count_matches_persona_count() -> None:
    """len(result) == len(personas) - the critical positional invariant."""
    from alphaswarm.simulation import _dispatch_enriched_sub_waves

    mock_governor = MagicMock()
    mock_client = MagicMock()
    mock_settings = MagicMock()

    async def _side_effect(**kwargs):
        personas_arg = kwargs["personas"]
        return [_make_decision(SignalType.BUY, p["agent_id"]) for p in personas_arg]

    with patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock, side_effect=_side_effect):
        result = await _dispatch_enriched_sub_waves(
            personas=TEST_PERSONAS,
            market_snapshots=MARKET_SNAPSHOTS,
            rumor=RUMOR,
            governor=mock_governor,
            client=mock_client,
            model="test-model",
            settings=mock_settings,
        )

    assert len(result) == len(TEST_PERSONAS)
