"""scripts/fetch_ticker_map.py writes a validated SEC map atomically (no real network)."""

from __future__ import annotations

import json
from collections.abc import Coroutine
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from tests.support.scripts import load_script

PAYLOAD = {"0": {"cik_str": 1, "ticker": "ZZZT", "title": "ZZZT Holdings Inc."}}


def _load() -> ModuleType:
    return load_script("fetch_ticker_map")


async def test_fetch_sends_the_user_agent_and_writes_the_payload(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["User-Agent"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json=PAYLOAD)

    script = _load()
    dest = tmp_path / "cache" / "sec_tickers.json"
    count = await script.fetch("AlphaSwarm research test@example.invalid", dest, transport=httpx.MockTransport(handler))
    assert count == 1
    assert seen == {"ua": "AlphaSwarm research test@example.invalid", "url": script.SEC_URL}
    assert json.loads(dest.read_text(encoding="utf-8")) == PAYLOAD


async def test_fetch_refuses_an_unusable_payload(tmp_path: Path) -> None:
    script = _load()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"0": {"ticker": "x"}}))
    dest = tmp_path / "sec_tickers.json"
    try:
        await script.fetch("ua", dest, transport=transport)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert not dest.exists()


def test_main_writes_to_the_requested_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load()
    calls: list[tuple[str, Path]] = []

    async def fake_fetch(user_agent: str, dest: Path) -> int:
        calls.append((user_agent, dest))
        return 3

    def drive(coro: Coroutine[object, object, int]) -> int:
        # asyncio.run would open a socketpair, which pytest-socket blocks.
        try:
            coro.send(None)
        except StopIteration as stop:
            return int(stop.value)
        raise AssertionError("fake_fetch should not suspend")

    monkeypatch.setattr(script, "fetch", fake_fetch)
    monkeypatch.setattr(script, "asyncio", SimpleNamespace(run=drive))
    dest = tmp_path / "map.json"
    assert script.main(["--user-agent", "AlphaSwarm research test@example.invalid", "--output", str(dest)]) == 0
    assert calls == [("AlphaSwarm research test@example.invalid", dest)]
    assert f"wrote 3 tickers to {dest}" in capsys.readouterr().out
