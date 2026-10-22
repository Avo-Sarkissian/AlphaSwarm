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


def test_neo4j_job_requires_the_database() -> None:
    job = _jobs(_text(CI))["backend-neo4j"]
    assert "image: neo4j:5.26-community" in job
    assert "NEO4J_AUTH: neo4j/alphaswarm-test-only" in job
    assert "7688:7687" in job
    assert "-m neo4j --require-neo4j" in job
    assert "-rxX" in job


def test_lint_job_runs_the_static_gates() -> None:
    job = _jobs(_text(CI))["lint"]
    for command in (
        "uv run mypy src",
        "uv run lint-imports",
        "uv run vulture src vulture_whitelist.py --min-confidence 80",
    ):
        assert command in job, command


def test_frontend_job_runs_eslint_before_the_unit_tests() -> None:
    job = _jobs(_text(CI))["frontend"]
    assert "run: npm run lint" in job
    assert job.index("run: npm run lint") < job.index("run: npx vitest run")
