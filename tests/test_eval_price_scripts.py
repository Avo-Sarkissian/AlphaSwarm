"""Fixture builder and outcome labeller scripts (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from alphaswarm.context_formatter import format_market_context
from alphaswarm.evaluation import (
    EvalPaths,
    FixtureHeadline,
    OutcomeLabel,
    PricePoint,
    points_from_rows,
    read_jsonl,
    write_jsonl,
)
from alphaswarm.ingestion.fixture import ANON_LABEL, load_context_fixture
from tests.support.eval_data import (
    PREMARKET_EVENT,
    PRICE_DAYS,
    alternating_series,
    flat_series,
    make_event,
    write_events,
)
from tests.support.eval_scripts import load_eval_script

build_fixtures = load_eval_script("build_fixtures")
label_outcomes = load_eval_script("label_outcomes")
EVENT = make_event(1, when=PREMARKET_EVENT)


class FakeDownload:
    """Returns every bar of the fictional series, even ones after the requested window."""

    def __init__(self, series: dict[str, list[PricePoint]]) -> None:
        self.series = series
        self.requests: list[tuple[str, date, date, bool]] = []

    def __call__(self, ticker: str, start: date, end: date, auto_adjust: bool) -> list[PricePoint]:
        self.requests.append((ticker, start, end, auto_adjust))
        return list(self.series.get(ticker, []))


def test_points_from_rows_skips_bad_bars() -> None:
    rows = [
        (date(2026, 1, 6), 10.0, 5.0),
        (date(2026, 1, 5), float("nan"), 1.0),
        (date(2026, 1, 7), -1.0, None),
        (date(2026, 1, 8), 11.0, float("nan")),
    ]
    assert points_from_rows(rows) == [
        PricePoint(day=date(2026, 1, 6), close=10.0, volume=5),
        PricePoint(day=date(2026, 1, 8), close=11.0, volume=None),
    ]


def test_fixture_never_keeps_a_bar_after_the_event() -> None:
    download = FakeDownload({"ZZZT": alternating_series(0.05)})
    packet = build_fixtures.fixture_for(EVENT, download, [])
    expected = alternating_series(0.05)[21]  # PRICE_DAYS[21]: the last close before 08:00 ET
    assert packet.market[0].price is not None
    assert float(packet.market[0].price) == pytest.approx(round(expected.close, 2))
    assert packet.market[0].volume == expected.volume
    assert packet.as_of == EVENT.timestamp
    ((ticker, _, end, auto_adjust),) = download.requests
    assert ticker == "ZZZT" and auto_adjust is False
    assert end == PRICE_DAYS[22] + timedelta(days=1)  # never asks beyond the event's own day


def test_fixture_after_an_early_close_keeps_that_session() -> None:
    event = make_event(1, when=datetime(2025, 11, 28, 19, 0, tzinfo=UTC))  # 14:00 EST
    bars = [
        PricePoint(day=date(2025, 11, 26), close=10.0, volume=1),
        PricePoint(day=date(2025, 11, 28), close=11.0, volume=2),  # closed at 13:00 EST
    ]
    packet = build_fixtures.fixture_for(event, FakeDownload({"ZZZT": bars}), [])
    assert (packet.market[0].price, packet.market[0].volume) == (Decimal("11.00"), 2)


def test_only_headlines_published_before_the_event_are_kept() -> None:
    before = [
        FixtureHeadline(published_at=EVENT.timestamp - timedelta(hours=h), title=f"Fictional item {h}")
        for h in range(10, 0, -1)
    ]
    after = FixtureHeadline(published_at=EVENT.timestamp, title="Fictional leak at the event time")
    titles = build_fixtures.eligible_headlines(EVENT, [after, *before])
    assert len(titles) == build_fixtures.MAX_FIXTURE_HEADLINES
    assert titles[-1] == "Fictional item 1" and "Fictional leak" not in " ".join(titles)


def test_build_all_writes_named_and_anonymized_and_respects_force(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    write_events(paths.events, [EVENT, make_event(2)])
    paths.headlines.mkdir(parents=True)
    headline = FixtureHeadline(published_at=EVENT.timestamp - timedelta(days=1), title="ZZZT Holdings item")
    paths.headline_file(EVENT.event_id).write_text(headline.model_dump_json() + "\n", encoding="utf-8")
    download = FakeDownload({"ZZZT": alternating_series(0.05)})  # no QQQX bars -> evt-002 fails
    lines: list[str] = []
    events = read_jsonl(paths.events, type(EVENT))
    assert build_fixtures.build_all(events, paths=paths, download=download, force=False, out=lines.append) == (1, 1)
    named = load_context_fixture(paths.fixture("evt-001", "named"), not_after=EVENT.timestamp)
    anon = load_context_fixture(paths.fixture("evt-001", "anon"), not_after=EVENT.timestamp)
    assert named.news[0].headlines == ("ZZZT Holdings item",)
    assert anon.entities == (ANON_LABEL,) and "ZZZT" not in paths.fixture("evt-001", "anon").read_text()
    assert any(line.startswith("[fail] evt-002") for line in lines)
    assert build_fixtures.build_all(events[:1], paths=paths, download=download, force=False, out=lines.append) == (0, 0)
    assert build_fixtures.build_all(events[:1], paths=paths, download=download, force=True, out=lines.append) == (1, 0)


def test_every_stored_headline_reaches_the_market_block(tmp_path: Path) -> None:
    """An over-full curation keeps exactly the lines the formatter renders, newest included."""
    paths = EvalPaths(tmp_path)
    curated = [
        FixtureHeadline(
            published_at=EVENT.timestamp - timedelta(hours=h),
            title=f"ZZZT Holdings fictional item {h}",
        )
        for h in range(8, 0, -1)
    ]
    blank = FixtureHeadline(published_at=EVENT.timestamp - timedelta(minutes=30), title="<>")
    paths.headlines.mkdir(parents=True)
    paths.headline_file(EVENT.event_id).write_text(
        "".join(h.model_dump_json() + "\n" for h in [*curated, blank]), encoding="utf-8"
    )
    lines: list[str] = []
    download = FakeDownload({"ZZZT": alternating_series(0.05)})
    assert build_fixtures.build_all([EVENT], paths=paths, download=download, force=False, out=lines.append) == (1, 0)
    block = format_market_context(load_context_fixture(paths.fixture("evt-001", "named")))
    assert block is not None
    rendered = [line for line in block.splitlines() if line.startswith("  - ")]
    assert "  - ZZZT Holdings fictional item 1" in rendered  # the newest pre-event title
    (ok,) = [line for line in lines if line.startswith("[ok] evt-001")]
    assert ok.endswith(f", {len(rendered)} headlines")


def test_label_event_uses_auto_adjusted_closes_and_the_benchmark() -> None:
    download = FakeDownload({"ZZZT": alternating_series(0.05), "IVV": flat_series()})
    label = label_outcomes.label_event(EVENT, download)
    assert label.label_1d == "up" and label.abn_ret_1d == pytest.approx(0.05, abs=1e-6)
    assert {r[0] for r in download.requests} == {"ZZZT", "IVV"}
    assert all(r[3] is True for r in download.requests)
    start, end = label_outcomes.label_window(EVENT)
    assert (start, end) == (
        date(2026, 2, 4) - timedelta(days=60),
        date(2026, 2, 4) + timedelta(days=15),
    )


def test_label_all_keeps_existing_and_reports_failures() -> None:
    old = OutcomeLabel(
        event_id="evt-009",
        abn_ret_1d=0.0,
        abn_ret_5d=0.0,
        vol_scale=0.01,
        label_1d="flat",
        label_5d="flat",
    )
    short = make_event(2, when=PREMARKET_EVENT)  # QQQX has only 10 bars -> insufficient history
    download = FakeDownload(
        {
            "ZZZT": alternating_series(0.05),
            "QQQX": alternating_series(0.05)[:10],
            "IVV": flat_series(),
        }
    )
    lines: list[str] = []
    labels, failed = label_outcomes.label_all([EVENT, short], [old], download=download, out=lines.append)
    assert failed == 1 and set(labels) == {"evt-001", "evt-009"}
    assert any(line.startswith("[fail] evt-002") for line in lines)


def test_label_main_writes_in_event_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = EvalPaths(tmp_path)
    second = make_event(2, when=PREMARKET_EVENT)
    write_events(paths.events, [EVENT, second])
    write_jsonl(paths.labels, [])
    monkeypatch.setattr(label_outcomes, "PATHS", paths)
    fake = FakeDownload({"ZZZT": alternating_series(0.05), "QQQX": alternating_series(-0.05), "IVV": flat_series()})
    monkeypatch.setattr(label_outcomes, "yfinance_closes", fake)
    assert label_outcomes.main([]) == 0
    written = [json.loads(line) for line in paths.labels.read_text().splitlines()]
    assert [w["event_id"] for w in written] == ["evt-001", "evt-002"]
    assert [w["label_1d"] for w in written] == ["up", "down"]
    assert not math.isnan(written[0]["vol_scale"])
