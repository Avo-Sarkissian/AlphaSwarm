"""Swarm-side ticker resolution (docs/DECISIONS.md#adr-ticker-resolution)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphaswarm.ingestion.tickers import (
    TickerResolver,
    load_ticker_resolver,
    normalize_company_name,
)
from alphaswarm.types import EntityType, SeedEntity, SeedEvent

# Fictional SEC-shaped payload (fictional tickers only); the dash ticker is skipped.
SEC_PAYLOAD = {
    "0": {"cik_str": 1, "ticker": "ZZZT", "title": "ZZZT Holdings Inc."},
    "1": {"cik_str": 2, "ticker": "QQQX", "title": "QQQX Robotics Corp"},
    "2": {"cik_str": 3, "ticker": "XQZW", "title": "XQZW Industrial Group"},
    "3": {"cik_str": 4, "ticker": "ZQXY", "title": "The Zeta Quantum Labs, Ltd."},
    "4": {"cik_str": 5, "ticker": "QZZX-B", "title": "QZZX Class B Shares"},
}
SEC = TickerResolver.from_sec_payload(SEC_PAYLOAD)


def _company(name: str, ticker: str | None = None, kind: EntityType = EntityType.COMPANY) -> SeedEntity:
    return SeedEntity(name=name, type=kind, relevance=0.8, sentiment=0.1, ticker=ticker)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ZZZT Holdings Inc.", "zzzt"),
        ("QQQX Robotics Corp", "qqqx robotics"),
        ("The Zeta Quantum Labs, Ltd.", "zeta quantum labs"),
        ("Q&Z Partners Co", "q and z partners"),
        ("   ", ""),
    ],
)
def test_normalize_company_name(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


def test_sec_payload_is_indexed_by_ticker_and_name() -> None:
    assert SEC.source == "sec"
    assert sorted(SEC.tickers) == ["QQQX", "XQZW", "ZQXY", "ZZZT"]
    assert SEC.by_name["qqqx robotics"] == "QQQX"


def test_sec_map_accepts_agreeing_symbols_and_resolves_names() -> None:
    assert SEC.resolve(_company("ZZZT Holdings", "ZZZT")) == "ZZZT"
    assert SEC.resolve(_company("QQQX Robotics")) == "QQQX"
    assert SEC.resolve(_company("Zeta Quantum Labs", "ZQXY")) == "ZQXY"


def test_sec_map_rejects_a_symbol_whose_title_disagrees() -> None:
    assert SEC.resolve(_company("Private Robotics Startup", "QQQX")) is None


def test_a_shared_generic_first_word_is_not_agreement() -> None:
    first = TickerResolver.from_sec_payload(
        {"0": {"cik_str": 9, "ticker": "QZZX", "title": "First Quantum Widgets Inc."}}
    )
    assert first.resolve(_company("First Zeta Solar", "QZZX")) is None
    assert first.resolve(_company("First Quantum", "QZZX")) == "QZZX"


def test_only_companies_get_tickers() -> None:
    assert SEC.resolve(_company("Industrial Automation", "XQZW", EntityType.SECTOR)) is None
    assert TickerResolver.empty().resolve(_company("A Fictional CEO", "ZZZT", EntityType.PERSON)) is None


def test_acronyms_are_dropped_without_a_map() -> None:
    empty = TickerResolver.empty()
    assert empty.source == "none"
    assert empty.resolve(_company("Federal Reserve", "FED")) is None
    assert empty.resolve(_company("OPEC", "OPEC")) is None
    assert empty.resolve(_company("ZZZT Holdings", "ZZZT")) == "ZZZT"


def test_builtin_aliases_need_the_symbol_in_the_map() -> None:
    assert TickerResolver.empty().resolve(_company("Google")) == "GOOGL"
    assert SEC.resolve(_company("Google")) is None  # GOOGL is not in this fictional SEC map


def test_resolve_seed_event_replaces_every_ticker() -> None:
    event = SeedEvent(
        raw_rumor="r",
        entities=[_company("ZZZT Holdings", "ZZZT"), _company("Private Robotics Startup", "QQQX")],
        overall_sentiment=0.2,
    )
    resolved = SEC.resolve_seed_event(event)
    assert [e.ticker for e in resolved.entities] == ["ZZZT", None]
    assert [e.ticker for e in event.entities] == ["ZZZT", "QQQX"]  # input untouched


def test_from_sec_payload_rejects_unusable_payloads() -> None:
    with pytest.raises(ValueError):
        TickerResolver.from_sec_payload([1, 2])
    with pytest.raises(ValueError):
        TickerResolver.from_sec_payload({"0": {"ticker": "TOO-LONG", "title": "x"}})


async def test_load_ticker_resolver_never_raises(tmp_path: Path) -> None:
    assert (await load_ticker_resolver(tmp_path / "absent.json")).source == "none"
    good = tmp_path / "sec_tickers.json"
    good.write_text(json.dumps(SEC_PAYLOAD), encoding="utf-8")
    assert (await load_ticker_resolver(good)).source == "sec"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert (await load_ticker_resolver(bad)).source == "none"
