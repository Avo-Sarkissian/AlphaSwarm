"""run --context-fixture / --no-market-context (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphaswarm import cli
from alphaswarm.ingestion.fixture import build_fixture_packet
from alphaswarm.ingestion.types import Fundamentals

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
PACKET = build_fixture_packet(
    event_id="evt-001",
    as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
    ticker="ZZZT",
    close=Decimal("123.45"),
    volume=1_000_000,
)


def _fixture(tmp_path: Path, packet: Any = PACKET) -> Path:
    path = tmp_path / "evt-001.json"
    path.write_text(packet.model_dump_json(), encoding="utf-8")
    return path


def test_plain_run_keeps_the_one_argument_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "_handle_run", calls.append)
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_OK
    assert calls == [RUMOR]


def test_context_fixture_is_loaded_and_passed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def handler(rumor: str, **kwargs: Any) -> None:
        seen.update(kwargs, rumor=rumor)

    monkeypatch.setattr(cli, "_handle_run", handler)
    assert cli.run_cli(["run", RUMOR, "--context-fixture", str(_fixture(tmp_path))]) == cli.EXIT_OK
    assert seen == {"rumor": RUMOR, "context_fixture": PACKET}


def test_no_market_context_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "_handle_run", lambda rumor, **kw: seen.update(kw))
    assert cli.run_cli(["run", RUMOR, "--no-market-context"]) == cli.EXIT_OK
    assert seen == {"market_context": False}


def test_invalid_fixture_exits_2_before_the_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    called: list[str] = []
    monkeypatch.setattr(cli, "_handle_run", lambda rumor, **kw: called.append(rumor))
    leaky = PACKET.model_copy(
        update={"market": (PACKET.market[0].model_copy(update={"fundamentals": Fundamentals(pe_ratio=Decimal("20"))}),)}
    )
    code = cli.run_cli(["run", RUMOR, "--context-fixture", str(_fixture(tmp_path, leaky))])
    assert code == cli.EXIT_USAGE
    assert called == []
    assert "fundamentals" in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, "{}"], ids=["missing", "not_a_packet"])
def test_unreadable_fixture_exits_2_before_the_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    path = tmp_path / "x.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    called: list[str] = []
    monkeypatch.setattr(cli, "_handle_run", lambda rumor, **kw: called.append(rumor))
    assert cli.run_cli(["run", RUMOR, "--context-fixture", str(path)]) == cli.EXIT_USAGE
    assert called == []
    assert "--context-fixture" in capsys.readouterr().err


def test_flags_are_mutually_exclusive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["run", RUMOR, "--context-fixture", str(_fixture(tmp_path)), "--no-market-context"]
    assert cli.run_cli(argv) == cli.EXIT_USAGE
    assert "not allowed with argument" in capsys.readouterr().err
