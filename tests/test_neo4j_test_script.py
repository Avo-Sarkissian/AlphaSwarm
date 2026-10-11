"""scripts/neo4j_test.sh only ever targets the throwaway neo4j-test service.

A fake `docker` on PATH records its arguments, so no daemon is needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "neo4j_test.sh"


def _run(
    tmp_path: Path, *args: str, password: str | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s | %s\\n" "$*" "${ALPHASWARM_NEO4J__PASSWORD:-}" >> "$FAKE_DOCKER_LOG"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_DOCKER_LOG": str(log)}
    if password is not None:
        env["ALPHASWARM_NEO4J__PASSWORD"] = password
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, calls


def test_down_names_the_test_service_so_the_dev_container_survives(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "down")
    assert proc.returncode == 0, proc.stderr
    assert calls == ["compose --profile test down neo4j-test | unused-by-neo4j-test"]


def test_up_waits_for_health_with_a_placeholder_password(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "up")
    assert proc.returncode == 0, proc.stderr
    assert calls == ["compose --profile test up -d --wait neo4j-test | unused-by-neo4j-test"]


def test_an_exported_password_passes_through_unchanged(tmp_path: Path) -> None:
    _proc, calls = _run(tmp_path, "status", password="fictional-dev-value")
    assert calls == ["compose --profile test ps neo4j-test | fictional-dev-value"]


def test_reset_recreates_only_the_test_service(tmp_path: Path) -> None:
    _proc, calls = _run(tmp_path, "reset")
    assert [c.split(" | ")[0] for c in calls] == [
        "compose --profile test down neo4j-test",
        "compose --profile test up -d --wait neo4j-test",
    ]


@pytest.mark.parametrize("args", [(), ("purge",)])
def test_unknown_commands_exit_2_without_calling_docker(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    proc, calls = _run(tmp_path, *args)
    assert proc.returncode == 2
    assert calls == []
    assert "usage:" in proc.stderr
