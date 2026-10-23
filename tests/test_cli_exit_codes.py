"""CLI exit codes, verbosity and bare-command help (docs/DECISIONS.md#adr-cli-ux)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

import pytest

from alphaswarm import cli
from alphaswarm.errors import InferenceConfigError

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def raising(exc: BaseException) -> Callable[..., None]:
    def handler(*_args: object) -> None:
        raise exc

    return handler


def test_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "_handle_run", calls.append)
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_OK
    assert calls == [RUMOR]


def test_async_handler_runs_in_an_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def handler(rumor: str) -> None:
        seen.append(rumor)

    monkeypatch.setattr(cli, "_handle_inject", handler)
    assert cli.run_cli(["inject", RUMOR]) == cli.EXIT_OK
    assert seen == [RUMOR]


def test_keyboard_interrupt_exits_130_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_handle_run", raising(KeyboardInterrupt()))
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_INTERRUPTED == 130
    err = capsys.readouterr().err
    assert "Interrupted." in err
    assert "Traceback" not in err


def test_runtime_failure_exits_1_with_a_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_handle_run", raising(RuntimeError("boom")))
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: boom" in captured.err
    assert "-v" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("argv", [["-v", "run", RUMOR], ["run", "-v", RUMOR], ["run", "--verbose", RUMOR]])
def test_verbose_prints_the_traceback(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_handle_run", raising(RuntimeError("boom")))
    assert cli.run_cli(argv) == cli.EXIT_FAILURE
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" in err
    assert "RuntimeError: boom" in err


def test_settings_validation_error_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from alphaswarm.settings import AppSettings

    def handler(rumor: str) -> None:
        AppSettings(_env_file=None, log_level="NOT_A_LEVEL")  # type: ignore[call-arg]

    monkeypatch.setattr(cli, "_handle_run", handler)
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_USAGE
    assert capsys.readouterr().err.startswith("Configuration error:")


def test_inference_config_error_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_handle_run", raising(InferenceConfigError("inference config is invalid")))
    assert cli.run_cli(["run", RUMOR]) == cli.EXIT_USAGE


def test_usage_error_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run_cli(["report", "--bogus"]) == cli.EXIT_USAGE
    assert "usage: alphaswarm" in capsys.readouterr().err


def test_bare_command_prints_help_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run_cli([]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: alphaswarm")
    for name in ("inject", "run", "report", "web"):
        assert name in captured.out
    assert captured.err == ""


def test_main_exits_with_the_runner_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_handle_run", raising(RuntimeError("boom")))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["run", RUMOR])
    assert exc_info.value.code == cli.EXIT_FAILURE
    cli.main([])  # success returns normally


def test_handler_system_exit_passes_through(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A handler that exits on purpose keeps its code and its own message."""

    def handler(rumor: str) -> None:
        print("Error: Neo4j is not reachable.", file=sys.stderr)
        raise SystemExit(1)

    monkeypatch.setattr(cli, "_handle_run", handler)
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["run", RUMOR])
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err == "Error: Neo4j is not reachable.\n"


@pytest.mark.slow
def test_real_sigint_exits_130() -> None:
    """A real Ctrl-C inside asyncio.run (as in `alphaswarm run`) exits 130 after cleanup."""
    script = (
        "import asyncio, os, signal, sys\n"
        "from alphaswarm import cli\n"
        "async def handler(rumor):\n"
        "    try:\n"
        "        os.kill(os.getpid(), signal.SIGINT)\n"
        "        await asyncio.sleep(30)\n"
        "    finally:\n"
        "        print('cleanup ran', file=sys.stderr)\n"
        "cli._handle_run = handler\n"
        "sys.exit(cli.run_cli(['run', 'ZZZT test rumor']))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=50,
        env=dict(os.environ),
    )
    assert proc.returncode == 130
    assert "cleanup ran" in proc.stderr
    assert "Interrupted." in proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.mark.slow
def test_python_m_alphaswarm_without_arguments_prints_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "alphaswarm"],
        capture_output=True,
        text=True,
        timeout=50,
        env=dict(os.environ),
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("usage: alphaswarm")
