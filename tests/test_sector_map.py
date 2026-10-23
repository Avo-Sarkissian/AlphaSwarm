"""The advisory's sector map is local data, not source.

Fictional data only (docs/DECISIONS.md#adr-holdings-isolation). The owner's map
lives in the gitignored data/sector_map.local.json and is never read by tests
(hermetic_env redirects it).
"""

from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import alphaswarm.advisory.sector_map as sector_map_module
from alphaswarm.advisory.sector_map import (
    EMPTY_SECTOR_MAP,
    SECTOR_MAP_EXAMPLE_PATH,
    UNKNOWN_SECTOR,
    load_sector_map,
)
from alphaswarm.settings import PROJECT_ROOT, AppSettings

FICTIONAL = {"ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX"}
ENTRY: dict[str, Any] = {
    "sector": "Industrial Automation",
    "region_exposure": "global",
    "supply_chain_sensitivity": "high",
    "macro_beta": 0.9,
}
EXAMPLE = load_sector_map(Path("/nonexistent/sector_map.local.json"))


class _RecordingLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))

    info = warning = error = debug = _record


def _write(path: Path, payload: object) -> Path:
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def test_example_file_is_fictional_and_complete() -> None:
    assert EXAMPLE.source == "example"
    assert set(EXAMPLE.entries) == FICTIONAL
    assert dict(EXAMPLE.aliases) == {"zzzt holdings": "ZZZT", "qqqx robotics": "QQQX"}


def test_missing_local_map_uses_the_example(tmp_path: Path) -> None:
    """A fresh clone has no local map and still gets sectors."""
    sector_map = load_sector_map(tmp_path / "absent.json")
    assert sector_map.source == "example"
    assert set(sector_map.entries) == FICTIONAL


def test_local_map_wins_and_keys_are_normalized(tmp_path: Path) -> None:
    local = _write(
        tmp_path / "local.json",
        {"tickers": {" zzzt ": ENTRY}, "aliases": {"  ZZZT Holdings ": "zzzt"}},
    )
    sector_map = load_sector_map(local)
    assert sector_map.source == "local"
    assert dict(sector_map.entries) == {"ZZZT": ENTRY}
    assert dict(sector_map.aliases) == {"zzzt holdings": "ZZZT"}


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        {"tickers": {"ZZZT": {**ENTRY, "macro_beta": 1.5}}},
        {"tickers": {"ZZZT": ENTRY}, "aliases": {"qqqx robotics": "QQQX"}},
        {"tickers": {"ZZZT": {**ENTRY, "region_exposure": "Mars"}}},
        {"tickers": {"not a ticker": ENTRY}},
        {"tickers": {"ZZZT": ENTRY}, "extra": True},
    ],
    ids=["not-json", "beta-out-of-range", "alias-to-unknown", "bad-region", "bad-key", "extra-key"],
)
def test_malformed_local_map_falls_back_to_empty_and_logs_no_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    """An owner typo yields an empty map, never fictional sectors."""
    recorder = _RecordingLog()
    monkeypatch.setattr(sector_map_module, "log", recorder)
    sector_map = load_sector_map(_write(tmp_path / "local.json", payload))
    assert sector_map is EMPTY_SECTOR_MAP
    [(event, fields)] = recorder.events
    assert event == "sector_map_invalid"
    assert set(fields) == {"source", "error_type", "hint"}
    assert fields["source"] == "local"
    assert "ZZZT" not in json.dumps(fields)


def test_successful_load_logs_counts_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingLog()
    monkeypatch.setattr(sector_map_module, "log", recorder)
    load_sector_map(_write(tmp_path / "local.json", {"tickers": {"ZZZT": ENTRY}}))
    assert recorder.events == [("sector_map_loaded", {"source": "local", "entries": 1, "aliases": 0})]


@pytest.mark.parametrize("use_example", [True, False], ids=["example", "none"])
def test_fallback_loads_carry_a_setup_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_example: bool,
) -> None:
    """Without a local map the log tells the owner how to add one (no tickers, no paths)."""
    recorder = _RecordingLog()
    monkeypatch.setattr(sector_map_module, "log", recorder)
    example = SECTOR_MAP_EXAMPLE_PATH if use_example else None
    load_sector_map(tmp_path / "absent.json", example=example)
    [(event, fields)] = recorder.events
    assert event == "sector_map_loaded"
    assert fields["source"] == ("example" if use_example else "none")
    assert "data/sector_map.local.json" in fields["hint"]
    assert not any(ticker in fields["hint"] for ticker in FICTIONAL)
    assert str(tmp_path) not in json.dumps(fields)


def test_no_map_at_all_is_empty(tmp_path: Path) -> None:
    assert load_sector_map(tmp_path / "absent.json", example=None) is EMPTY_SECTOR_MAP
    assert EMPTY_SECTOR_MAP.lookup("ZZZT") == UNKNOWN_SECTOR


@given(st.text(alphabet=string.ascii_letters + string.digits + ".-", max_size=8))
def test_lookup_is_case_insensitive_and_total(raw: str) -> None:
    info = EXAMPLE.lookup(raw)
    assert info == EXAMPLE.lookup(raw.upper()) == EXAMPLE.lookup(raw.lower())
    assert info in [*EXAMPLE.entries.values(), UNKNOWN_SECTOR]


@given(st.text(max_size=40), st.frozensets(st.sampled_from(sorted(FICTIONAL)), max_size=5))
def test_resolve_ticker_only_returns_held_tickers(name: str, held: frozenset[str]) -> None:
    resolved = EXAMPLE.resolve_ticker(name, held)
    assert resolved is None or resolved in held


def test_pass_through_and_aliases_need_a_held_ticker() -> None:
    assert EXAMPLE.resolve_ticker("zzzt", {"ZZZT"}) == "ZZZT"
    assert EXAMPLE.resolve_ticker("ZZZT Holdings", {"ZZZT"}) == "ZZZT"
    assert EXAMPLE.resolve_ticker("ZZZT Holdings", {"QQQX"}) is None
    assert EXAMPLE.resolve_ticker("Industrial Automation", {"ZZZT"}) is None
    assert EXAMPLE.resolve_ticker("   ", {"ZZZT"}) is None
    assert EMPTY_SECTOR_MAP.resolve_ticker("xqzw", {"XQZW"}) == "XQZW"  # no map needed


def test_settings_point_at_the_gitignored_local_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHASWARM_SECTOR_MAP_PATH", raising=False)
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.sector_map_path == Path("data/sector_map.local.json")
    assert "/data/" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert SECTOR_MAP_EXAMPLE_PATH == PROJECT_ROOT / "examples" / "sector_map.example.json"


async def test_advisory_job_loads_the_map_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each advisory run reads settings.sector_map_path, so edits apply without a restart."""
    from types import SimpleNamespace

    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.inference.types import ProviderRole
    from tests.inference.fakes import FakeInferenceProvider
    from tests.support.web_app import CYCLE_A, advisory_service_for, route_test_settings

    settings = route_test_settings(tmp_path)
    _write(settings.sector_map_path, {"tickers": {"ZZZT": ENTRY}})
    captured: dict[str, Any] = {}

    async def _synthesize(**kwargs: Any) -> Any:
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    provider = FakeInferenceProvider(role=ProviderRole.ORCHESTRATOR, model="fake", scripted=[])
    monkeypatch.setattr("alphaswarm.services.advisory.synthesize", _synthesize)
    monkeypatch.setattr(
        "alphaswarm.inference.factory.build_providers",
        lambda *_a, **_k: BuiltProviders(
            orchestrator=provider,  # type: ignore[arg-type]
            worker=provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        ),
    )
    # A loopback Ollama whose model is local, so the advisory's cloud guards pass.
    service = advisory_service_for(settings, portfolio=SimpleNamespace(holdings=("fictional",)))
    with pytest.raises(RuntimeError, match="stop after capture"):
        await service.generate(CYCLE_A)
    assert captured["sector_map"].source == "local"
    assert set(captured["sector_map"].entries) == {"ZZZT"}
