"""Outcome labels follow New York sessions (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

import pytest

from alphaswarm.evaluation import (
    InsufficientHistoryError,
    PricePoint,
    base_index,
    compute_outcome,
    session_close_utc,
)


def business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


DAYS = business_days(date(2026, 1, 5), 30)  # DAYS[21] = 2026-02-03 (Tue), DAYS[22] = 2026-02-04


def ticker_series(event_move: float) -> list[PricePoint]:
    """Alternating +1%/-1% daily before the event, *event_move* on DAYS[22], flat after."""
    closes = [100.0]
    for i in range(1, 22):
        closes.append(closes[-1] * (1.01 if i % 2 else 0.99))
    closes.append(closes[-1] * (1.0 + event_move))
    closes.extend([closes[-1]] * (len(DAYS) - len(closes)))
    return [PricePoint(day=d, close=c, volume=1000) for d, c in zip(DAYS, closes, strict=True)]


BENCHMARK = [PricePoint(day=d, close=100.0) for d in DAYS]
PREMARKET = datetime(2026, 2, 4, 13, 0, tzinfo=UTC)  # 08:00 EST on DAYS[22]


def test_session_close_handles_both_offsets() -> None:
    assert session_close_utc(date(2026, 2, 3)) == datetime(2026, 2, 3, 21, 0, tzinfo=UTC)
    assert session_close_utc(date(2026, 3, 9)) == datetime(2026, 3, 9, 20, 0, tzinfo=UTC)


def test_base_close_follows_new_york_sessions_and_dst() -> None:
    feb = DAYS
    assert base_index(feb, datetime(2026, 2, 3, 21, 0, tzinfo=UTC)) == 21  # exactly at the close
    assert base_index(feb, datetime(2026, 2, 3, 20, 59, tzinfo=UTC)) == 20  # one minute before
    assert base_index(feb, PREMARKET) == 21  # pre-market reacts on the same day
    assert base_index(feb, datetime(2026, 2, 3, 22, 0, tzinfo=UTC)) == 21  # after the close
    assert base_index(feb, datetime(2026, 2, 7, 15, 0, tzinfo=UTC)) == 24  # Saturday -> Friday
    march = [date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)]
    assert base_index(march, datetime(2026, 3, 9, 20, 30, tzinfo=UTC)) == 1  # EDT close 20:00Z
    assert base_index(march, datetime(2026, 3, 9, 19, 59, tzinfo=UTC)) == 0
    with pytest.raises(InsufficientHistoryError):
        base_index(march, datetime(2026, 3, 6, 15, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    ("day", "close_utc_hour"),
    [
        (date(2023, 7, 3), 17),  # Monday before Independence Day: 13:00 EDT
        (date(2025, 7, 3), 17),  # Thursday before Independence Day
        (date(2025, 11, 28), 18),  # day after Thanksgiving: 13:00 EST
        (date(2026, 11, 27), 18),
        (date(2025, 12, 24), 18),  # Christmas Eve on a Wednesday
        (date(2026, 7, 2), 20),  # July 3 2026 is the observed holiday: a full session
        (date(2025, 11, 26), 21),  # the day before Thanksgiving is a full session
        (date(2022, 12, 23), 21),  # Christmas Eve on a Saturday: no early close
    ],
)
def test_early_close_days_close_at_13_00_new_york(day: date, close_utc_hour: int) -> None:
    assert session_close_utc(day) == datetime.combine(day, time(close_utc_hour), tzinfo=UTC)


def test_an_event_after_an_early_close_uses_that_session() -> None:
    days = [date(2025, 11, 26), date(2025, 11, 28), date(2025, 12, 1)]
    assert base_index(days, datetime(2025, 11, 28, 19, 0, tzinfo=UTC)) == 1  # 14:00 EST
    assert base_index(days, datetime(2025, 11, 28, 17, 59, tzinfo=UTC)) == 0  # 12:59 EST


@pytest.mark.parametrize(("move", "label"), [(0.05, "up"), (-0.05, "down"), (0.002, "flat")])
def test_labels_use_the_volatility_scaled_flat_zone(move: float, label: str) -> None:
    outcome = compute_outcome("evt-001", PREMARKET, ticker_series(move), BENCHMARK)
    assert outcome.vol_scale == pytest.approx(0.01 * math.sqrt(20 / 19), abs=1e-6)
    assert outcome.abn_ret_1d == pytest.approx(move, abs=1e-6)
    assert outcome.abn_ret_5d == pytest.approx(move, abs=1e-6)
    assert outcome.label_1d == label
    assert outcome.label_5d == label


def test_benchmark_return_is_subtracted() -> None:
    bench = [PricePoint(day=d, close=100.0 if i < 22 else 103.0) for i, d in enumerate(DAYS)]
    outcome = compute_outcome("evt-001", PREMARKET, ticker_series(0.05), bench)
    assert outcome.abn_ret_1d == pytest.approx(0.02, abs=1e-6)


def test_days_missing_from_either_series_are_dropped() -> None:
    bench = [p for p in BENCHMARK if p.day != DAYS[5]]
    outcome = compute_outcome("evt-001", PREMARKET, ticker_series(0.05), bench)
    assert outcome.label_1d == "up"


def _cut(series: Sequence[PricePoint], keep: slice) -> list[PricePoint]:
    return list(series)[keep]


def test_insufficient_history_is_reported() -> None:
    with pytest.raises(InsufficientHistoryError, match="before the event"):
        compute_outcome("evt-001", PREMARKET, _cut(ticker_series(0.05), slice(5, None)), BENCHMARK)
    with pytest.raises(InsufficientHistoryError, match="after the event"):
        compute_outcome("evt-001", PREMARKET, _cut(ticker_series(0.05), slice(0, 25)), BENCHMARK)
