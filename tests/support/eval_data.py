"""Fictional eval events for tests (reserved tickers only; docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

from alphaswarm.evaluation import EvalEvent, PricePoint

TICKERS: Final[tuple[str, ...]] = ("ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX")
CATEGORIES: Final[tuple[str, ...]] = ("m_and_a", "earnings", "guidance", "regulatory", "product")
WORKER_RELEASE: Final = date(2026, 3, 1)
TODAY: Final = date(2026, 10, 8)
FIRST_EVENT: Final = datetime(2026, 2, 2, 14, 30, tzinfo=UTC)


def make_event(index: int, *, when: datetime | None = None, **overrides: object) -> EvalEvent:
    """Event ``evt-{index:03d}``: weekly from 2026-02-02 14:30Z, post-cutoff after 2026-03-01,
    categories cycling through five values (at most 4 each for 16 events)."""
    ticker = TICKERS[(index - 1) % len(TICKERS)]
    timestamp = when if when is not None else FIRST_EVENT + timedelta(days=7 * (index - 1))
    data: dict[str, object] = {
        "event_id": f"evt-{index:03d}",
        "timestamp": timestamp.isoformat(),
        "rumor": (
            f"{ticker} Holdings is reported to be exploring a sale of its robotics unit "
            f"(fictional event {index})."
        ),
        "primary_ticker": ticker,
        "benchmark": "SPY",
        "category": CATEGORIES[(index - 1) % len(CATEGORIES)],
        "post_cutoff": timestamp.date() > WORKER_RELEASE,
        "anonymized_rumor": (
            "A mid-cap industrial company is reported to be exploring a sale of its robotics "
            f"unit (fictional event {index})."
        ),
    }
    data.update(overrides)
    return EvalEvent.model_validate(data)


def make_events(count: int) -> list[EvalEvent]:
    return [make_event(index) for index in range(1, count + 1)]


def write_events(path: Path, events: Sequence[EvalEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(event.model_dump_json() + "\n" for event in events), encoding="utf-8")


def business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


PRICE_DAYS: Final = business_days(date(2026, 1, 5), 30)  # [21] = 2026-02-03, [22] = 2026-02-04
PREMARKET_EVENT: Final = datetime(2026, 2, 4, 13, 0, tzinfo=UTC)  # 08:00 EST on PRICE_DAYS[22]


def alternating_series(move: float, *, days: Sequence[date] = PRICE_DAYS) -> list[PricePoint]:
    """+1%/-1% daily up to index 21, *move* on index 22, flat afterwards (volume 1000 + index)."""
    closes = [100.0]
    for i in range(1, 22):
        closes.append(closes[-1] * (1.01 if i % 2 else 0.99))
    closes.append(closes[-1] * (1.0 + move))
    closes.extend([closes[-1]] * (len(days) - len(closes)))
    return [
        PricePoint(day=d, close=c, volume=1000 + i)
        for i, (d, c) in enumerate(zip(days, closes, strict=True))
    ]


def flat_series(level: float = 100.0, *, days: Sequence[date] = PRICE_DAYS) -> list[PricePoint]:
    return [PricePoint(day=d, close=level) for d in days]
