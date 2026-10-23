"""CI wiring invariants: the gates the docs promise are actually in the workflow files."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _jobs(text: str) -> dict[str, str]:
    """Top-level jobs keyed by name (two-space-indented keys under ``jobs:``)."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z0-9-]+):\n", body)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def _steps(job: str) -> list[str]:
    """A job's steps, each as its YAML text (the six-space-indented items under ``steps:``)."""
    return re.split(r"(?m)^      - ", job.split("\n    steps:\n", 1)[1])[1:]


def _run(step: str) -> str:
    """A step's ``run:`` command, without the YAML block indicator (``|`` or ``>-``)."""
    lines = step.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("run:") or line.startswith("        run:"):
            value = line.split("run:", 1)[1].strip()
            body = [] if value in ("|", "|-", ">", ">-") else [value]
            for more in lines[i + 1 :]:
                if more.strip() and not more.startswith(" " * 10):
                    break
                body.append(more.strip())
            return "\n".join(body)
    return ""


def test_ci_has_the_expected_jobs() -> None:
    assert set(_jobs(_text(CI))) == {"lint", "backend-unit", "backend-neo4j", "frontend"}


def test_every_job_is_time_boxed_and_locked() -> None:
    text = _text(CI)
    for name, job in _jobs(text).items():
        assert "timeout-minutes: 15" in job, name
    assert all("--locked" in line for line in re.findall(r"uv sync[^\n]*", text))
    assert "\npermissions:\n  contents: read\n" in text
    assert "cancel-in-progress: true" in text
    assert "--ignore=" not in text


def test_unit_job_gates_coverage_and_deselects_external_suites() -> None:
    job = _jobs(_text(CI))["backend-unit"]
    assert '-m "not neo4j and not live_network and not ollama"' in job
    assert "--cov-branch" in job
    assert "--cov-fail-under=85" in job
    assert "-rxX" in job


def test_neo4j_job_requires_the_database() -> None:
    job = _jobs(_text(CI))["backend-neo4j"]
    assert "image: neo4j:5.26-community" in job
    assert "NEO4J_AUTH: neo4j/alphaswarm-test-only" in job
    assert "7688:7687" in job
    assert "-m neo4j --require-neo4j" in job
    assert "-rxX" in job


def test_piped_steps_fail_when_the_first_command_fails() -> None:
    """Every step that pipes a command (``pytest ... | tee``) declares ``shell: bash``.

    GitHub runs an explicit ``shell: bash`` as ``bash --noprofile --norc -eo pipefail``,
    but the default shell is ``bash -e`` without pipefail. There the step reports
    tee's exit status, so a failing suite, the coverage gate or ``--require-neo4j``
    would all show green.
    """
    pytest_steps = 0
    for path in (CI, WORKFLOWS / "nightly.yml"):
        for job_name, job in _jobs(_text(path)).items():
            for step in _steps(job):
                command = _run(step)
                pytest_steps += "uv run pytest" in command
                unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "", command)  # grep -E '(A|B)' is no pipe
                if re.search(r"(?<!\|)\|(?!\|)", unquoted):
                    where = f"{path.name} {job_name}: {step.splitlines()[0]}"
                    assert re.search(r"(?m)^        shell: bash$", step), where
    assert pytest_steps == 3  # backend-unit, backend-neo4j, nightly live-network


def test_lint_job_runs_the_static_gates() -> None:
    job = _jobs(_text(CI))["lint"]
    for command in (
        "uv run mypy src",
        "uv run lint-imports",
        "uv run vulture src vulture_whitelist.py --min-confidence 80",
        "uv run ruff check src tests",
        "uv run ruff format --check src tests",
    ):
        assert command in job, command


def test_pre_commit_runs_ruff_and_import_linter() -> None:
    config = _text(REPO / ".pre-commit-config.yaml")
    for hook in ("id: ruff-check", "id: ruff-format", "id: lint-imports"):
        assert hook in config, hook


def test_frontend_job_runs_eslint_before_the_unit_tests() -> None:
    job = _jobs(_text(CI))["frontend"]
    assert "run: npm run lint" in job
    assert job.index("run: npm run lint") < job.index("run: npx vitest run")


def test_frontend_job_uses_node_22_and_audits_production_deps() -> None:
    job = _jobs(_text(CI))["frontend"]
    assert "node-version-file: frontend/.nvmrc" in job
    assert "npm audit --omit=dev --audit-level=high" in job
    assert "tsc -b --noEmit" not in job  # npm run build already runs tsc -b
    assert (REPO / "frontend" / ".nvmrc").read_text(encoding="utf-8").strip() == "22"


def test_live_tests_run_nightly_and_never_on_push() -> None:
    nightly = WORKFLOWS / "nightly.yml"
    assert nightly.exists()
    text = _text(nightly)
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "--run-live -m live_network" in text
    assert "timeout-minutes: 15" in text
    assert "\npermissions:\n  contents: read\n" in text
    assert "--run-live" not in _text(CI)
