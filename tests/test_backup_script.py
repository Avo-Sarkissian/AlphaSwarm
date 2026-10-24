"""scripts/backup_neo4j.sh: refuses mid-run, stops gracefully, prints a restore that works.

Fake `docker` and `curl` executables on PATH stand in for the real ones; the
fake neo4j-admin enforces the real rule that `database load` only reads a file
named neo4j.dump. No test touches a real container or the real backup
directory (docs/RUNBOOK.md section 3).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from alphaswarm.instance_lock import acquire
from alphaswarm.settings import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "backup_neo4j.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
needs_python = pytest.mark.skipif(
    shutil.which("python3") is None and shutil.which("uv") is None,
    reason="the lock check runs through python3 (or uv)",
)

FAKE_DOCKER = r"""#!/bin/bash
echo "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  container)
    if [[ "$3" == "--format" ]]; then
      case "$4" in
        *Image*) echo "sha256:fakeimage" ;;
        *Running*) echo "true" ;;
        *) exit 1 ;;
      esac
      exit 0
    fi
    [[ " ${FAKE_CONTAINERS:-alphaswarm-neo4j} " == *" $3 "* ]] && exit 0
    exit 1 ;;
  stop|start) exit 0 ;;
  run)
    host=""; prev=""
    for arg in "$@"; do
      if [[ "$prev" == "-v" && "$arg" == *:/backups ]]; then host="${arg%:/backups}"; fi
      prev="$arg"
    done
    if [[ " $* " == *" database dump "* ]]; then
      printf 'fake neo4j store' > "$host/neo4j.dump"; exit 0
    fi
    if [[ " $* " == *" database load "* ]]; then
      [[ -s "$host/neo4j.dump" ]] || { echo "neo4j.dump not found in /backups" >&2; exit 1; }
      exit 0
    fi
    exit 1 ;;
esac
exit 0
"""

FAKE_CURL = r"""#!/bin/bash
echo "$*" >> "$FAKE_CURL_LOG"
if [[ -n "${FAKE_HEALTH:-}" ]]; then printf '%s' "$FAKE_HEALTH"; exit 0; fi
exit 7
"""

RUNNING = '{"status":"ok","is_simulation_running":true}'
IDLE = '{"status":"ok","is_simulation_running":false}'


@dataclass
class Harness:
    tmp: Path
    bin: Path
    script: Path  # a copy inside tmp/repo, so even a broken version never touches data/backups
    backups: Path
    lock: Path

    @property
    def docker_log(self) -> Path:
        return self.tmp / "docker.log"

    def env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("ALPHASWARM_NEO4J_CONTAINER", None)
        env.update(
            {
                "PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_CURL_LOG": str(self.tmp / "curl.log"),
                "ALPHASWARM_BACKUP_DIR": str(self.backups),
                "ALPHASWARM_INSTANCE_LOCK": str(self.lock),
                "ALPHASWARM_HEALTH_URL": "http://127.0.0.1:65530/api/health",
            }
        )
        env.update(extra)
        return env

    def run(self, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script)],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def docker_calls(self) -> list[str]:
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        exe = bin_dir / name
        exe.write_text(body, encoding="utf-8")
        exe.chmod(0o755)
    # The script cds to its parent's parent; run a copy so its relative default
    # (data/backups) and its pruning stay inside tmp_path whatever version it is.
    script = tmp_path / "repo" / "scripts" / "backup_neo4j.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)
    return Harness(
        tmp=tmp_path,
        bin=bin_dir,
        script=script,
        backups=tmp_path / "backups",
        lock=tmp_path / "instance.lock",
    )


def test_the_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_refuses_while_the_web_server_runs_a_simulation(harness: Harness) -> None:
    result = harness.run(FAKE_HEALTH=RUNNING)
    assert result.returncode == 75
    assert "simulation is running" in result.stderr
    assert not [c for c in harness.docker_calls() if c.startswith(("stop", "run"))]


@needs_python
def test_refuses_while_a_cli_command_holds_the_instance_lock(harness: Harness) -> None:
    holder = acquire("run", path=harness.lock)
    try:
        result = harness.run()
    finally:
        holder.release()
    assert result.returncode == 75
    assert "`alphaswarm run` is running" in result.stderr
    assert not [c for c in harness.docker_calls() if c.startswith("stop")]


@needs_python
def test_an_idle_web_server_does_not_block_the_backup(harness: Harness) -> None:
    holder = acquire("web", detail="http://127.0.0.1:8000", path=harness.lock)
    try:
        result = harness.run(FAKE_HEALTH=IDLE)
    finally:
        holder.release()
    assert result.returncode == 0, result.stderr
    calls = harness.docker_calls()
    assert "stop -t 60 alphaswarm-neo4j" in calls
    assert "start alphaswarm-neo4j" in calls
    assert len(list(harness.backups.glob("neo4j-*.dump"))) == 1
    assert not (harness.backups / "neo4j.dump").exists()


def test_no_answer_from_the_server_is_not_a_reason_to_refuse(harness: Harness) -> None:
    result = harness.run()
    assert result.returncode == 0, result.stderr
    assert len(list(harness.backups.glob("neo4j-*.dump"))) == 1


def _restore_steps(stdout: str) -> list[str]:
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Restore this backup"))
    return [line.strip() for line in lines[start + 1 :] if line.startswith("  ")]


def test_the_printed_restore_sequence_loads_the_backup(harness: Harness) -> None:
    """The printed sequence works against the fake; the owner verifies it on a scratch container."""
    steps = _restore_steps(harness.run().stdout)
    assert len(steps) == 5
    assert steps[0] == 'RESTORE_DIR="$(mktemp -d)"'
    assert steps[1].startswith("cp ") and steps[1].endswith('"$RESTORE_DIR/neo4j.dump"')
    assert steps[2] == "docker stop -t 60 alphaswarm-neo4j"
    assert "neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true" in steps[3]
    assert steps[4] == "docker start alphaswarm-neo4j"
    replay = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", "\n".join(steps)],
        env=harness.env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert replay.returncode == 0, replay.stderr
    assert any(" database load " in f" {call} " for call in harness.docker_calls())


def test_the_old_printed_restore_would_have_failed(harness: Harness) -> None:
    """Loading straight from the backup directory finds no neo4j.dump (docs/BACKLOG.md 1.6)."""
    harness.run()
    old = (
        f"docker run --rm --volumes-from alphaswarm-neo4j -v {harness.backups}:/backups "
        "sha256:fakeimage neo4j-admin database load neo4j --from-path=/backups "
        "--overwrite-destination=true"
    )
    replay = subprocess.run(["bash", "-c", old], env=harness.env(), capture_output=True, text=True)
    assert replay.returncode == 1


def test_the_hand_made_neo4j_container_is_found_by_name(harness: Harness) -> None:
    """A database created with `docker run --name neo4j` (not Compose) is backed up as is."""
    result = harness.run(FAKE_CONTAINERS="neo4j")
    assert result.returncode == 0, result.stderr
    calls = harness.docker_calls()
    assert "stop -t 60 neo4j" in calls
    assert "start neo4j" in calls
    steps = _restore_steps(result.stdout)
    assert steps[2] == "docker stop -t 60 neo4j"
    assert steps[4] == "docker start neo4j"


def test_two_candidate_containers_are_never_guessed(harness: Harness) -> None:
    result = harness.run(FAKE_CONTAINERS="alphaswarm-neo4j neo4j")
    assert result.returncode == 1
    assert "more than one Neo4j container exists" in result.stderr
    assert not [c for c in harness.docker_calls() if c.startswith(("stop", "run"))]


def test_an_explicit_container_name_wins(harness: Harness) -> None:
    result = harness.run(FAKE_CONTAINERS="alphaswarm-neo4j neo4j", ALPHASWARM_NEO4J_CONTAINER="neo4j")
    assert result.returncode == 0, result.stderr
    assert "stop -t 60 neo4j" in harness.docker_calls()


def test_an_unknown_explicit_container_is_an_error(harness: Harness) -> None:
    result = harness.run(ALPHASWARM_NEO4J_CONTAINER="no-such-container")
    assert result.returncode == 1
    assert "no container named 'no-such-container'" in result.stderr
