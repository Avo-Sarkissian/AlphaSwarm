"""docs/experiments.md is final: filled, linked and honest."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.support.markdown import h2_sections
from tests.support.scripts import load_script

ROOT: Final = Path(__file__).resolve().parents[1]
EXPERIMENTS: Final = ROOT / "docs" / "experiments.md"


def _experiments() -> str:
    return EXPERIMENTS.read_text(encoding="utf-8")


def test_headline_table_is_complete() -> None:
    docs_sync = load_script("docs_sync")
    assert set(docs_sync.parse_headline(_experiments())) == set(docs_sync.HEADLINE_KEYS)


def test_no_section_is_left_unrun_or_unfilled() -> None:
    lines = _experiments().splitlines()
    unrun = [n for n, line in enumerate(lines, 1) if re.fullmatch(r"\s*Not (run|measured) yet\.?\s*", line)]
    slots = [n for n, line in enumerate(lines, 1) if re.search(r"<[A-Z][A-Z0-9_]+>", line)]
    assert (unrun, slots) == ([], [])


# The README and the CHANGELOG copy these cells verbatim (docs/DECISIONS.md#adr-docs-sync), so
# they never name phase or item ids of the private planning documents or the planning process.
_PLANNING_WORDS: Final = re.compile(r"\b[PT]\d+(?:\.\d+)*\b|(?i:\bdeferred\b)")


def test_headline_cells_name_no_planning_ids_or_process() -> None:
    rows = load_script("docs_sync").parse_headline(_experiments())
    leaks = []
    for key, row in rows.items():
        cells = f"{row.label} | {row.value} | {row.source}"
        if _PLANNING_WORDS.search(cells):
            leaks.append(f"{key}: {cells}")
    assert leaks == []


def test_model_benchmarks_match_the_modelfiles() -> None:
    worker = (ROOT / "modelfiles" / "Modelfile.worker").read_text(encoding="utf-8")
    orchestrator = (ROOT / "modelfiles" / "Modelfile.orchestrator").read_text(encoding="utf-8")
    section = dict(h2_sections(_experiments()))["Model stack benchmarks (2026-06-11)"]
    figures = (
        ("422", worker),
        ("833", worker),
        ("2361", worker),
        ("111", orchestrator),
        ("3395", orchestrator),
    )
    for figure, modelfile in figures:
        assert re.search(rf"prefill\s+{figure} t/s", modelfile), figure
        assert f"{int(figure):,}" in section, figure


METHODOLOGY: Final = ROOT / "docs" / "methodology.md"


def test_methodology_states_limitations_and_how_to_reproduce() -> None:
    titles = [title for title, _ in h2_sections(METHODOLOGY.read_text(encoding="utf-8"))]
    assert "Limitations" in titles and "Reproduce" in titles


def test_results_docs_link_each_other() -> None:
    assert "](methodology.md" in _experiments()
    assert "](experiments.md" in METHODOLOGY.read_text(encoding="utf-8")
