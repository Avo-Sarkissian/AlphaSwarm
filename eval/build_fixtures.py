#!/usr/bin/env python3
"""Build point-in-time context fixtures for the eval events (docs/DECISIONS.md#adr-eval-harness).

    uv run python eval/build_fixtures.py                          # every event without a fixture
    uv run python eval/build_fixtures.py --events evt-001,evt-002 --force

Per event: the last close and volume whose 16:00 New York session ended at or before
the event timestamp (yfinance, split-adjusted; bars after it are dropped) and the
curated headlines in eval/headlines/<event_id>.jsonl published before the event.
Writes eval/fixtures/<event_id>.json and the anonymized <event_id>.anon.json.
Existing fixtures are committed evidence and are kept unless --force.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from alphaswarm.evaluation import (
    NEW_YORK,
    EvalEvent,
    EvalPaths,
    FixtureHeadline,
    InsufficientHistoryError,
    PricePoint,
    points_from_rows,
    read_jsonl,
    read_jsonl_if_exists,
    session_close_utc,
)
from alphaswarm.ingestion.fixture import anonymize_packet, build_fixture_packet
from alphaswarm.ingestion.types import ContextPacket

EVAL_DIR: Final = Path(__file__).resolve().parent
PATHS: Final = EvalPaths(EVAL_DIR)
LOOKBACK_DAYS: Final = 14
MAX_FIXTURE_HEADLINES: Final = 8

Download = Callable[[str, date, date, bool], list[PricePoint]]


def yfinance_closes(ticker: str, start: date, end: date, auto_adjust: bool) -> list[PricePoint]:
    """Daily bars in [start, end) from yfinance (network; owner's shell only)."""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(
        start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=auto_adjust
    )
    return points_from_rows(
        (stamp.date(), row["Close"], row.get("Volume")) for stamp, row in frame.iterrows()
    )


def fixture_window(event: EvalEvent) -> tuple[date, date]:
    """[start, end) of the requested bars: end is the day after the event's New York date."""
    local_day = event.timestamp.astimezone(NEW_YORK).date()
    return local_day - timedelta(days=LOOKBACK_DAYS), local_day + timedelta(days=1)


def eligible_headlines(event: EvalEvent, headlines: Sequence[FixtureHeadline]) -> list[str]:
    """Titles published strictly before the event, oldest first, at most the last 8."""
    before = sorted(
        (h for h in headlines if h.published_at < event.timestamp), key=lambda h: h.published_at
    )
    return [h.title for h in before][-MAX_FIXTURE_HEADLINES:]


def fixture_for(
    event: EvalEvent, download: Download, headlines: Sequence[FixtureHeadline]
) -> ContextPacket:
    start, end = fixture_window(event)
    bars = [
        p
        for p in download(event.primary_ticker, start, end, False)
        if session_close_utc(p.day) <= event.timestamp
    ]
    if not bars:
        raise InsufficientHistoryError(
            f"{event.event_id}: no {event.primary_ticker} close at or before the event"
        )
    last = max(bars, key=lambda p: p.day)
    return build_fixture_packet(
        event_id=event.event_id,
        as_of=event.timestamp,
        ticker=event.primary_ticker,
        close=Decimal(f"{last.close:.2f}"),
        volume=last.volume,
        headlines=eligible_headlines(event, headlines),
    )


def _write(path: Path, packet: ContextPacket) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")


def build_all(
    events: Sequence[EvalEvent],
    *,
    paths: EvalPaths,
    download: Download,
    force: bool,
    out: Callable[[str], object] = print,
) -> tuple[int, int]:
    """Write fixtures for *events*; returns (written, failed)."""
    written = failed = 0
    for event in events:
        if paths.fixture(event.event_id, "named").exists() and not force:
            out(f"[skip] {event.event_id}: fixture exists (use --force to rebuild)")
            continue
        try:
            headlines = read_jsonl_if_exists(paths.headline_file(event.event_id), FixtureHeadline)
            packet = fixture_for(event, download, headlines)
            anonymized = anonymize_packet(packet)
        except ValueError as exc:
            out(f"[fail] {event.event_id}: {exc}")
            failed += 1
            continue
        _write(paths.fixture(event.event_id, "named"), packet)
        _write(paths.fixture(event.event_id, "anon"), anonymized)
        count = len(packet.news[0].headlines) if packet.news else 0
        out(f"[ok] {event.event_id}: close {packet.market[0].price}, {count} headlines")
        written += 1
    return written, failed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_fixtures",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--events", default="", help="comma-separated event ids (default: all)")
    parser.add_argument("--force", action="store_true", help="rebuild fixtures that exist")
    args = parser.parse_args(argv)
    events = read_jsonl(PATHS.events, EvalEvent)
    wanted = {e for e in args.events.split(",") if e}
    if wanted:
        events = [e for e in events if e.event_id in wanted]
    written, failed = build_all(events, paths=PATHS, download=yfinance_closes, force=args.force)
    print(f"wrote {written} named + {written} anonymized fixtures; {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
