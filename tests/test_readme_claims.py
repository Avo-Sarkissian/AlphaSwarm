"""The README must not contradict the code (Phase 0 slice of T12.1 / T12.2).

These patterns stay forbidden after any later README rewrite. Messages report
line numbers and the reason, so a failure says exactly what to fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphaswarm.config import DEFAULT_BRACKETS, InferenceConfig

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
    (
        r"(?i)space-insensitive",
        "holdings CSV header names ignore case and surrounding spaces only (holdings/loader.py)",
    ),
    (
        r"(?i)no data leaves|never leaves? (your|the) machine",
        "cloud roles send prompts off-machine; the advisory sends tickers after the opt-in",
    ),
)


def _lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("pattern", "reason"), FORBIDDEN_README_PATTERNS)
def test_readme_has_no_false_claim(pattern: str, reason: str) -> None:
    hits = [n for n, line in enumerate(_lines(), start=1) if re.search(pattern, line)]
    assert hits == [], f"README.md lines {hits}: {reason}"


def test_readme_says_to_restart_after_appending_to_dotenv() -> None:
    """create_app() reads .env once, at startup: a running server keeps the old values."""
    lines = _lines()
    for n, line in enumerate(lines):
        if re.search(r">>\s*\.env\b", line):
            following = "\n".join(lines[n : n + 8])
            assert re.search(r"(?i)\brestart (?:it|the (?:server|backend))\b", following), (
                f"README.md line {n + 1} appends to .env but does not say to restart the server"
            )


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


def test_readme_inference_config_example_passes_the_strict_models() -> None:
    """The README invites hand-editing .secrets/inference.json; its example must load.

    The stored config rejects unknown keys and out-of-range limits, so an example
    with a comment key or a renamed field would teach users to write a file the
    backend refuses.
    """
    blocks = re.findall(r"```json\n(.*?)```", README.read_text(encoding="utf-8"), flags=re.DOTALL)
    examples = [block for block in blocks if '"orchestrator"' in block and '"worker"' in block]
    assert examples, "README.md no longer shows an inference.json example; drop this test with it"
    for block in examples:
        try:
            InferenceConfig.model_validate_json(block)
        except ValidationError as exc:
            problems = [(err["loc"], err["type"]) for err in exc.errors(include_input=False, include_url=False)]
            pytest.fail(f"README.md inference.json example fails the config models: {problems}")


def test_env_example_never_sends_test_runs_to_the_dev_password() -> None:
    """Tests use the throwaway neo4j-test database, never the dev password, so the
    template must not tell anyone to export that secret into their shell."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "export ALPHASWARM_NEO4J__PASSWORD" not in text
    assert "tests/test_graph_integration.py" not in text


def test_env_example_lists_every_path_setting_and_the_advisory_retention() -> None:
    """The Paths block shows every path setting with its default, and the retention
    count the docs tell the owner to raise is listed too."""
    from alphaswarm.config import AppSettings

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    path_fields = {name: field for name, field in AppSettings.model_fields.items() if field.annotation is Path}
    assert "sector_map_path" in path_fields
    missing = [
        f"ALPHASWARM_{name.upper()}={field.default.as_posix()}"
        for name, field in path_fields.items()
        if f"# ALPHASWARM_{name.upper()}={field.default.as_posix()}" not in text
    ]
    assert missing == []
    keep_last = AppSettings.model_fields["advisory_keep_last"].default
    assert f"# ALPHASWARM_ADVISORY_KEEP_LAST={keep_last}" in text
