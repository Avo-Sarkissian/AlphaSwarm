"""Point-in-time ContextPacket fixtures (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from alphaswarm.context_formatter import format_market_context
from alphaswarm.ingestion.fixture import (
    ANON_LABEL,
    anonymize_packet,
    build_fixture_packet,
    load_context_fixture,
    validate_fixture,
)
from alphaswarm.ingestion.types import ContextPacket, Fundamentals

AS_OF = datetime(2026, 2, 3, 14, 0, tzinfo=UTC)
HEADLINE = "ZZZT Holdings names a new chief executive (fictional)"


def _packet(headlines: tuple[str, ...] = (HEADLINE,)) -> ContextPacket:
    return build_fixture_packet(
        event_id="evt-001",
        as_of=AS_OF,
        ticker="ZZZT",
        close=Decimal("123.45"),
        volume=1_000_000,
        headlines=headlines,
    )


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_fixture_renders_a_price_block_for_named_and_anonymized() -> None:
    named = _packet()
    block = format_market_context(named)
    assert block is not None
    assert "== ZZZT ==" in block and "Price: $123.45" in block and "chief executive" in block
    anon = anonymize_packet(named)
    anon_block = format_market_context(anon)
    assert anon_block is not None
    assert f"== {ANON_LABEL} ==" in anon_block and "Price: $123.45" in anon_block
    assert "ZZZT" not in anon.model_dump_json()
    assert anon.news == ()


def test_round_trip_through_a_file(tmp_path: Path) -> None:
    path = tmp_path / "evt-001.json"
    path.write_text(_packet().model_dump_json(indent=2), encoding="utf-8")
    assert load_context_fixture(path, not_after=AS_OF) == _packet()


def test_fixture_after_event_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "evt-001.json"
    path.write_text(_packet().model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="after the event"):
        load_context_fixture(path, not_after=AS_OF - timedelta(minutes=1))


def test_fixture_with_fundamentals_is_rejected() -> None:
    packet = _packet()
    leaky = packet.model_copy(
        update={"market": (packet.market[0].model_copy(update={"fundamentals": Fundamentals(pe_ratio=Decimal("20"))}),)}
    )
    with pytest.raises(ValueError, match="fundamentals"):
        validate_fixture(leaky, name="evt-001.json")


def test_naive_and_late_timestamps_are_rejected(tmp_path: Path) -> None:
    data = _packet().model_dump(mode="json")
    with pytest.raises(ValueError, match="timezone"):
        load_context_fixture(_write(tmp_path / "a.json", {**data, "as_of": "2026-02-03T14:00:00"}))
    late = dict(data)
    late["market"] = [{**data["market"][0], "fetched_at": "2026-02-03T15:00:00Z"}]
    with pytest.raises(ValueError, match="fetched after as_of"):
        load_context_fixture(_write(tmp_path / "b.json", late))


def test_unreadable_invalid_and_empty_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read context fixture"):
        load_context_fixture(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="is not a ContextPacket"):
        load_context_fixture(_write(tmp_path / "c.json", {"cycle_id": 1}))
    empty = {**_packet().model_dump(mode="json"), "market": [], "news": []}
    with pytest.raises(ValueError, match="no market or news data"):
        load_context_fixture(_write(tmp_path / "d.json", empty))


def test_builder_and_anonymizer_guard_their_inputs() -> None:
    with pytest.raises(ValueError, match="timezone"):
        build_fixture_packet(
            event_id="evt-001",
            as_of=datetime(2026, 2, 3, 14, 0),
            ticker="ZZZT",
            close=Decimal("1"),
            volume=None,
        )
    two = _packet().model_copy(update={"entities": ("ZZZT", "QQQX")})
    with pytest.raises(ValueError, match="one entity"):
        anonymize_packet(two)
    assert _packet(headlines=()).news == ()
