"""Deps helpers for point-in-time runs (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from structlog.testing import capture_logs

from alphaswarm.context_formatter import format_market_context
from alphaswarm.ingestion.fixture import build_fixture_packet
from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.simulation import SimulationDeps, apply_context_options, fixture_market_context

PACKET = build_fixture_packet(
    event_id="evt-001",
    as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
    ticker="ZZZT",
    close=Decimal("123.45"),
    volume=1_000_000,
)


def _deps(**overrides: Any) -> SimulationDeps:
    values: dict[str, Any] = {
        f.name: MagicMock(name=f.name)
        for f in dataclasses.fields(SimulationDeps)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    }
    values.update(market=FakeMarketDataProvider(), news=FakeNewsProvider())
    values.update(overrides)
    return SimulationDeps(**values)


def test_context_fixture_defaults_to_none() -> None:
    assert _deps().context_fixture is None


def test_fixture_drops_live_providers_and_keeps_everything_else() -> None:
    deps = _deps()
    result = apply_context_options(deps, fixture=PACKET)
    assert result.market is None and result.news is None
    assert result.context_fixture is PACKET
    for field in dataclasses.fields(SimulationDeps):
        if field.name not in {"market", "news", "context_fixture"}:
            assert getattr(result, field.name) is getattr(deps, field.name)
    assert deps.market is not None


def test_no_market_context_drops_providers_without_a_fixture() -> None:
    result = apply_context_options(_deps(context_fixture=PACKET), market_context=False)
    assert result.market is None and result.news is None and result.context_fixture is None


def test_default_returns_the_same_deps() -> None:
    deps = _deps()
    assert apply_context_options(deps) is deps


def test_fixture_and_no_market_context_conflict() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        apply_context_options(_deps(), fixture=PACKET, market_context=False)


def test_fixture_market_context_formats_and_logs() -> None:
    with capture_logs() as logs:
        block = fixture_market_context(PACKET, cycle_id="cycle-1")
    assert block == format_market_context(PACKET)
    assert any(
        entry["event"] == "context_fixture_used"
        and entry["rendered"] is True
        and entry["cycle_id"] == "cycle-1"
        and entry["as_of"] == PACKET.as_of.isoformat()
        and entry["entity_count"] == 1
        for entry in logs
    )
