#!/usr/bin/env python3
"""Label the eval events with 1- and 5-day abnormal returns (docs/DECISIONS.md#adr-eval-harness).

    uv run python eval/label_outcomes.py                   # all events -> eval/results/labels.jsonl
    uv run python eval/label_outcomes.py --events evt-004  # relabel some, keep the rest

Network: yfinance daily closes (auto-adjusted) for the ticker and its benchmark.
Labels are outcomes: they never enter a prompt, a fixture or a run.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from alphaswarm.evaluation import (
    NEW_YORK,
    EvalEvent,
    EvalPaths,
    OutcomeLabel,
    PricePoint,
    compute_outcome,
    points_from_rows,
    read_jsonl,
    read_jsonl_if_exists,
    write_jsonl,
)

EVAL_DIR: Final = Path(__file__).resolve().parent
PATHS: Final = EvalPaths(EVAL_DIR)
BEFORE_DAYS: Final = 60
AFTER_DAYS: Final = 15

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


def label_window(event: EvalEvent) -> tuple[date, date]:
    local_day = event.timestamp.astimezone(NEW_YORK).date()
    return local_day - timedelta(days=BEFORE_DAYS), local_day + timedelta(days=AFTER_DAYS)


def label_event(event: EvalEvent, download: Download) -> OutcomeLabel:
    start, end = label_window(event)
    return compute_outcome(
        event.event_id,
        event.timestamp,
        download(event.primary_ticker, start, end, True),
        download(event.benchmark, start, end, True),
    )


def label_all(
    events: Sequence[EvalEvent],
    existing: Sequence[OutcomeLabel],
    *,
    download: Download,
    out: Callable[[str], object] = print,
) -> tuple[dict[str, OutcomeLabel], int]:
    """Relabel *events*, keeping other existing labels; returns (labels by id, failures)."""
    labels = {label.event_id: label for label in existing}
    failed = 0
    for event in events:
        try:
            label = label_event(event, download)
        except ValueError as exc:
            out(f"[fail] {event.event_id}: {exc}")
            failed += 1
            continue
        labels[event.event_id] = label
        out(
            f"[ok] {event.event_id}: 1d {label.label_1d} ({label.abn_ret_1d:+.4f}), "
            f"5d {label.label_5d} ({label.abn_ret_5d:+.4f})"
        )
    return labels, failed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="label_outcomes",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--events", default="", help="comma-separated event ids (default: all)")
    args = parser.parse_args(argv)
    all_events = read_jsonl(PATHS.events, EvalEvent)
    wanted = {e for e in args.events.split(",") if e}
    selected = [e for e in all_events if not wanted or e.event_id in wanted]
    existing = read_jsonl_if_exists(PATHS.labels, OutcomeLabel)
    labels, failed = label_all(selected, existing, download=yfinance_closes)
    write_jsonl(PATHS.labels, [labels[e.event_id] for e in all_events if e.event_id in labels])
    print(f"labeled {len(selected) - failed}/{len(selected)} events -> {PATHS.labels}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
