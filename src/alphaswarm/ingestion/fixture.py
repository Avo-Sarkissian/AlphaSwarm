"""Point-in-time ContextPacket fixtures for evaluation runs (docs/DECISIONS.md#adr-eval-harness).

A fixture replaces the live yfinance/RSS fetch with a frozen packet built only from
data that existed before an event: the last close at or before the event timestamp
and curated headlines published before it. Fundamentals are refused because the
providers only expose current values, which would leak the future into a replay.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from alphaswarm.ingestion.types import ContextPacket, MarketSlice, NewsSlice

FIXTURE_SOURCE: Final = "eval_fixture"
ANON_LABEL: Final = "Subject company"


def _require_aware(value: datetime, what: str, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name}: {what} must carry a timezone")


def build_fixture_packet(
    *,
    event_id: str,
    as_of: datetime,
    ticker: str,
    close: Decimal,
    volume: int | None,
    headlines: Sequence[str] = (),
) -> ContextPacket:
    """One-entity packet: the last pre-event close and volume plus the given headlines."""
    _require_aware(as_of, "as_of", event_id)
    market = MarketSlice(
        ticker=ticker,
        price=close,
        volume=volume,
        fundamentals=None,
        fetched_at=as_of,
        source=FIXTURE_SOURCE,
        staleness="fresh",
    )
    news: tuple[NewsSlice, ...] = ()
    if headlines:
        news = (
            NewsSlice(
                entity=ticker,
                headlines=tuple(headlines),
                fetched_at=as_of,
                source=FIXTURE_SOURCE,
                staleness="fresh",
            ),
        )
    return ContextPacket(
        cycle_id=f"fixture:{event_id}",
        as_of=as_of,
        entities=(ticker,),
        market=(market,),
        news=news,
    )


def _names(token: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text) is not None


def anonymize_packet(packet: ContextPacket, *, label: str = ANON_LABEL) -> ContextPacket:
    """Same numbers under a neutral label; headlines dropped because they name the company."""
    if len(packet.entities) != 1:
        raise ValueError(
            f"{packet.cycle_id}: anonymize_packet expects one entity, got {len(packet.entities)}"
        )
    original = packet.entities[0]
    market = tuple(s.model_copy(update={"ticker": label}) for s in packet.market)
    anonymized = packet.model_copy(update={"entities": (label,), "market": market, "news": ()})
    if _names(original, anonymized.model_dump_json()):
        raise ValueError(f"{packet.cycle_id}: the anonymized packet still names {original}")
    return anonymized


def validate_fixture(
    packet: ContextPacket, *, not_after: datetime | None = None, name: str = "fixture"
) -> None:
    """Reject anything a point-in-time run must not see (docs/DECISIONS.md#adr-eval-harness)."""
    _require_aware(packet.as_of, "as_of", name)
    if not_after is not None and packet.as_of > not_after:
        raise ValueError(
            f"{name}: as_of {packet.as_of.isoformat()} is after the event ({not_after.isoformat()})"
        )
    if not packet.market and not packet.news:
        raise ValueError(f"{name}: no market or news data")
    for market_slice in packet.market:
        _require_aware(market_slice.fetched_at, f"{market_slice.ticker} fetched_at", name)
        if market_slice.fundamentals is not None:
            raise ValueError(
                f"{name}: {market_slice.ticker} carries fundamentals; the providers only expose "
                "current values, which would leak the future"
            )
        if market_slice.fetched_at > packet.as_of:
            raise ValueError(f"{name}: {market_slice.ticker} was fetched after as_of")
    for news_slice in packet.news:
        _require_aware(news_slice.fetched_at, f"{news_slice.entity} fetched_at", name)
        if news_slice.fetched_at > packet.as_of:
            raise ValueError(f"{name}: headlines for {news_slice.entity} were fetched after as_of")


def load_context_fixture(path: Path, *, not_after: datetime | None = None) -> ContextPacket:
    """Read and validate a fixture file; every problem is a ValueError naming the file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ValueError(f"cannot read context fixture {path}: {reason}") from exc
    try:
        packet = ContextPacket.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "document"
        raise ValueError(f"{path} is not a ContextPacket: {where}: {first['msg']}") from exc
    validate_fixture(packet, not_after=not_after, name=str(path))
    return packet
