"""The README must not contradict the code (Phase 0 slice of T12.1 / T12.2).

These patterns stay forbidden after any later README rewrite. Messages report
line numbers and the reason, so a failure says exactly what to fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from alphaswarm.config import DEFAULT_BRACKETS

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# (regex, why the claim is false). Searched line by line.
FORBIDDEN_README_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bTextual\b|\bTUI\b", "the Textual TUI was deleted; `start` launches the web UI"),
    (r"(?i)\bno cloud\b(?! credentials)", "optional cloud providers exist"),
    (r"(?i)no api keys|zero cloud dependencies", "cloud providers take API keys"),
    (r"(?i)entirely on local hardware|100% local", "cloud providers are opt-in, not absent"),
    (r"\b9B\b|35B orchestrator|Orchestrator \(35B\)", "orchestrator is 27B, worker 35B-A3B"),
    (
        r"\b(Sovereigns|Whales|whales|Suits|Insiders|Doom-Posters|Policy Wonks|policy wonks)\b",
        "v1 bracket names; the swarm uses the v2 composition",
    ),
    (r"report <cycle_id>", "the CLI takes `report --cycle <cycle_id>`"),
    (r"(?i)prebuilt `?dist/?`? ships", "frontend/dist/ is gitignored and must be built"),
    (r"\b(NewsAPI|EDGAR|Polygon|Reddit)\b", "only yfinance and RSS providers exist"),
    (r"(?i)post reads", "READ_POST edges are no longer written"),
    (r"(?i)force graph", "the graph uses a deterministic layout (DECISIONS.md#kr-41-1-01)"),
)


def _lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("pattern", "reason"), FORBIDDEN_README_PATTERNS)
def test_readme_has_no_false_claim(pattern: str, reason: str) -> None:
    hits = [n for n, line in enumerate(_lines(), start=1) if re.search(pattern, line)]
    assert hits == [], f"README.md lines {hits}: {reason}"


def test_readme_names_every_v2_bracket() -> None:
    text = README.read_text(encoding="utf-8")
    missing = [b.display_name for b in DEFAULT_BRACKETS if b.display_name not in text]
    assert missing == []


def test_readme_says_local_first_with_optional_cloud() -> None:
    text = README.read_text(encoding="utf-8").lower()
    assert "local-first" in text
    assert "optional cloud" in text


def test_readme_links_the_license_file() -> None:
    assert "](LICENSE)" in README.read_text(encoding="utf-8")


def test_readme_shows_no_prototype_screenshots() -> None:
    assert "docs/screenshots/" not in README.read_text(encoding="utf-8")
