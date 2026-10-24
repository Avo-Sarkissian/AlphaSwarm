"""scripts/export_cycle.py is a thin wrapper over `alphaswarm cycles export`."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from alphaswarm import cli

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_cycle.py"
CYCLE = "00000000-0000-4000-8000-0000000000a1"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_cycle_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_cycle_script"] = module
    spec.loader.exec_module(module)
    return module


def test_help_describes_the_export_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert _load().main(["--help"]) == cli.EXIT_OK
    assert capsys.readouterr().out.startswith("usage: alphaswarm cycles export")


def test_arguments_reach_cycles_export(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[argparse.Namespace] = []

    async def handler(args: argparse.Namespace) -> None:
        seen.append(args)

    monkeypatch.setattr(cli, "_handle_cycles", handler)
    assert _load().main([CYCLE, "-o", "out/cycle.json"]) == cli.EXIT_OK
    assert (seen[0].cycles_command, seen[0].cycle_id, seen[0].output) == ("export", CYCLE, "out/cycle.json")
