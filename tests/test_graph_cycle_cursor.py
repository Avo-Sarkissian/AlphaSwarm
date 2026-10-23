"""The cycle-listing cursor treats naive timestamps as UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from alphaswarm.graph import _as_utc


def test_naive_cursor_is_read_as_utc() -> None:
    result = _as_utc(datetime(2099, 1, 2, 12, 0))
    assert result == datetime(2099, 1, 2, 12, 0, tzinfo=UTC)
    assert result is not None and result.tzinfo is UTC


def test_aware_cursor_is_returned_unchanged() -> None:
    pacific = timezone(timedelta(hours=-7))
    cursor = datetime(2099, 1, 2, 5, 0, tzinfo=pacific)
    assert _as_utc(cursor) is cursor


def test_missing_cursor_stays_missing() -> None:
    assert _as_utc(None) is None
