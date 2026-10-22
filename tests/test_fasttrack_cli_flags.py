"""Fast-track run flags reach the handler (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphaswarm import cli
from alphaswarm.ingestion.fixture import build_fixture_packet

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
PACKET = build_fixture_packet(
    event_id="evt-001",
    as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
    ticker="ZZZT",
    close=Decimal("123.45"),
    volume=1_000_000,
)


def _capture(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "_handle_run", lambda rumor, **kw: seen.update(kw, rumor=rumor))
    monkeypatch.setattr(sys, "argv", ["alphaswarm", *argv])
    cli.main()
    return seen


def test_context_fixture_reaches_the_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "evt-001.json"
    path.write_text(PACKET.model_dump_json(), encoding="utf-8")
    seen = _capture(monkeypatch, ["run", RUMOR, "--context-fixture", str(path)])
    assert seen["rumor"] == RUMOR and seen["context_fixture"] == PACKET
    assert seen.get("market_context", True) is True


def test_no_market_context_reaches_the_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, ["run", RUMOR, "--no-market-context"])
    assert seen.get("market_context") is False and seen.get("context_fixture") is None


def test_plain_run_passes_no_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _capture(monkeypatch, ["run", RUMOR]) == {"rumor": RUMOR}


def test_invalid_fixture_exits_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys, "argv", ["alphaswarm", "run", RUMOR, "--context-fixture", str(tmp_path / "x.json")]
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
