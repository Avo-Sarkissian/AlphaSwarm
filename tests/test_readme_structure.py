"""The README follows the presentation skeleton and points only at things that exist."""

from __future__ import annotations

import contextlib
import io
import os
import re
from pathlib import Path
from typing import Final

import pytest

from alphaswarm.cli import build_parser
from alphaswarm.personas import DEFAULT_BRACKETS
from tests.support.markdown import h2_sections, links, preamble

ROOT: Final = Path(__file__).resolve().parents[1]
README: Final = ROOT / "README.md"
DISCLAIMER_TS: Final = ROOT / "frontend" / "src" / "features" / "advisory" / "disclaimer.ts"
HERO_GIF: Final = "docs/media/hero-cascade.gif"

README_SECTIONS: Final = (
    "Why it's interesting",
    "Architecture",
    "Quick start",
    "Results",
    "How it works",
    "Swarm composition",
    "Design decisions",
    "Testing & CI",
    "Security",
    "Limitations",
    "Roadmap",
    "Engineering process",
    "License",
)
QUICK_START_MUST_CONTAIN: Final = (
    "npm --prefix frontend ci && npm --prefix frontend run build",
    "./scripts/configure_ollama_app_env.sh",
    "ollama create alphaswarm-worker -f modelfiles/Modelfile.worker",
    "ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator",
    "docker compose up -d --wait neo4j",
    "uv run alphaswarm web",
)
EXECUTABLE_SCRIPTS: Final = (
    "scripts/configure_ollama_app_env.sh",
    "scripts/start_ollama.sh",
    "scripts/neo4j_test.sh",
)
REQUIRED_FILES: Final = (
    "modelfiles/Modelfile.worker",
    "modelfiles/Modelfile.orchestrator",
    "frontend/package-lock.json",
    "examples/holdings.example.csv",
)
# Decimals, thousands separators, percentages, multipliers and integers of 3+ digits.
MEASURED_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)+|\d+(?:\.\d+)?\s?(?:%|×)|\b\d{3,}\b")
_REPO_LINK: Final = re.compile(r"^(?!#)(?![a-z][a-z0-9+.-]*:)")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _sections() -> dict[str, str]:
    return dict(h2_sections(_readme()))


def _disclaimer() -> str:
    match = re.search(r"ADVISORY_DISCLAIMER\s*=\s*'([^']+)'", DISCLAIMER_TS.read_text(encoding="utf-8"))
    assert match, "ADVISORY_DISCLAIMER not found in disclaimer.ts"
    return match.group(1)


def _cli_accepts(*argv: str) -> bool:
    """True when `alphaswarm <argv>` parses (help exits 0); False on a usage error."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            build_parser().parse_args(list(argv))
        except SystemExit as exc:
            return exc.code == 0
    return True


def _quick_start_commands() -> list[str]:
    match = re.search(r"```bash\n(.*?)```", _sections()["Quick start"], re.S)
    assert match, "the Quick start has no bash block"
    lines = [re.sub(r"\s+#\s.*$", "", line).strip() for line in match.group(1).splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def test_readme_follows_the_skeleton() -> None:
    assert tuple(title for title, _ in h2_sections(_readme())) == README_SECTIONS


def test_readme_opens_with_the_pitch_and_the_demo_block() -> None:
    top = preamble(_readme())
    assert "<!-- demo:start -->" in top
    total = sum(b.count for b in DEFAULT_BRACKETS)
    assert f"{total} LLM personas in {len(DEFAULT_BRACKETS)} archetypes" in top


def test_readme_shows_the_hero_gif_only_once_it_exists() -> None:
    if (ROOT / HERO_GIF).is_file():
        assert f"]({HERO_GIF})" in preamble(_readme())
    else:
        assert HERO_GIF not in _readme()


def test_readme_quotes_the_ui_disclaimer() -> None:
    assert _disclaimer() in preamble(_readme())


def test_quick_start_is_five_commands() -> None:
    commands = _quick_start_commands()
    assert len(commands) == 5, commands
    joined = "\n".join(commands)
    assert [s for s in QUICK_START_MUST_CONTAIN if s not in joined] == []
    if _cli_accepts("doctor", "--help"):
        assert "uv run alphaswarm doctor" in commands[-1]


def test_quick_start_points_at_real_files() -> None:
    for script in EXECUTABLE_SCRIPTS:
        assert os.access(ROOT / script, os.X_OK), f"{script} is missing or not executable"
    for path in REQUIRED_FILES:
        assert (ROOT / path).is_file(), path
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"(?m)^ALPHASWARM_NEO4J__PASSWORD=$", env_example), "the Quick start sed needs this line"


def test_every_documented_subcommand_exists() -> None:
    subcommands = sorted(set(re.findall(r"uv run alphaswarm ([a-z]+)", _readme())))
    assert subcommands, "the README documents no alphaswarm subcommand"
    assert [s for s in subcommands if not _cli_accepts(s, "--help")] == []


@pytest.mark.parametrize("title", ["Why it's interesting", "Design decisions"])
def test_bullets_link_to_the_repository(title: str) -> None:
    bullets = [line for line in _sections()[title].splitlines() if line.startswith("- ")]
    assert bullets, f"'{title}' has no bullets"
    unlinked = [b for b in bullets if not any(_REPO_LINK.match(target) for _, target in links(b))]
    assert unlinked == []


def test_results_quote_only_the_generated_table() -> None:
    body = _sections()["Results"]
    assert "<!-- results:start -->" in body
    outside = re.sub(r"<!-- results:start -->.*?<!-- results:end -->", "", body, flags=re.S)
    stray = [ln for ln in outside.splitlines() if MEASURED_NUMBER.search(re.sub(r"\]\([^)]*\)", "]", ln))]
    assert stray == []


def test_architecture_has_a_mermaid_diagram() -> None:
    assert "```mermaid" in _sections()["Architecture"]


def test_operations_details_live_in_the_runbook() -> None:
    text = _readme()
    for moved in ("docker rm -f neo4j", "ALTER CURRENT USER", '"pricing_overrides"'):
        assert moved not in text, moved
