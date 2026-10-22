"""scripts/docs_sync.py renders the generated Markdown blocks from code and results."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from alphaswarm.config import DEFAULT_BRACKETS
from alphaswarm.types import BracketType
from tests.support.scripts import load_script


@pytest.fixture(scope="module")
def ds() -> ModuleType:
    return load_script("docs_sync")


# Fictional measurements: the shape of the real table, none of its values.
HEADLINE_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "eval_accuracy",
        "Swarm accuracy vs the best baseline",
        "hit rate 0.61 (95% CI 0.52-0.70) vs 0.50",
        "[Evaluation](#evaluation)",
    ),
    ("eval_verdict", "Evaluation verdict", "better", "[Evaluation](#evaluation)"),
    (
        "peer_effect",
        "Peer-attributable flip rate",
        "+6.0 pp (95% CI 2.1 to 9.8)",
        "[Control](#control)",
    ),
    ("peer_effect_verdict", "Peer-effect verdict", "positive", "[Control](#control)"),
    (
        "ablation_rounds",
        "2 vs 3 rounds",
        "no accuracy difference; 2 rounds 31% faster",
        "[Ablations](#ablations)",
    ),
    (
        "ablation_peers",
        "Peer strategy",
        "stratified 0.61 vs random 0.58 vs none 0.55",
        "[Ablations](#ablations)",
    ),
    (
        "peer_exposure",
        "Peer exposure before and after",
        "brackets never shown: 6 to 0",
        "[Decision](DECISIONS.md#adr-diverse-peer-context)",
    ),
    ("speedup", "Mean round time", "from 412 s to 268 s (-35%)", "[Arms](#arms)"),
    (
        "mlx_prefill_worker",
        "Worker prefill",
        "833 to 2,361 tok/s (2.8x)",
        "[Modelfile](../modelfiles/Modelfile.worker)",
    ),
    (
        "mlx_prefill_orchestrator",
        "Orchestrator prefill",
        "111 to 3,395 tok/s (30.6x)",
        "[Modelfile](../modelfiles/Modelfile.orchestrator)",
    ),
    (
        "model_weights",
        "Model memory",
        "worker 24 GB + orchestrator 22 GB",
        "[Budget](RUNBOOK.md#memory-budget)",
    ),
    ("wall_clock_3r", "3-round run", "31 min", "[Arms](#arms)"),
    ("wall_clock_2r", "2-round run", "21 min", "[Ablations](#ablations)"),
    ("backend_tests", "Backend tests", "1,512", "[Quality](#quality)"),
    ("backend_coverage", "Backend coverage", "89%", "[Quality](#quality)"),
    ("frontend_tests", "Frontend tests", "412", "[Quality](#quality)"),
    ("import_contracts", "Import-linter contracts kept", "5", "[Quality](#quality)"),
    ("demo_url", "Static demo", "https://example.invalid/demo/", "[Demo](#demo)"),
)


def headline_md(
    overrides: dict[str, str] | None = None,
    *,
    drop: tuple[str, ...] = (),
    extra: tuple[tuple[str, str, str, str], ...] = (),
) -> str:
    values = overrides or {}
    lines = [
        "# Experiments",
        "",
        "<!-- headline:start -->",
        "| Key | Result | Value | Source |",
        "|---|---|---|---|",
    ]
    for key, label, value, source in (*HEADLINE_ROWS, *extra):
        if key not in drop:
            lines.append(f"| `{key}` | {label} | {values.get(key, value)} | {source} |")
    lines += ["<!-- headline:end -->", ""]
    return "\n".join(lines)


def test_parse_headline_reads_every_row(ds: ModuleType) -> None:
    rows = ds.parse_headline(headline_md())
    assert list(rows) == list(ds.HEADLINE_KEYS)
    assert rows["speedup"].value == "from 412 s to 268 s (-35%)"
    assert rows["speedup"].source == "[Arms](#arms)"
    assert rows["speedup"].measured


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (headline_md(drop=("speedup",)), "missing keys: speedup"),
        (headline_md(extra=(("speedups", "x", "y", "z"),)), "unknown headline key: speedups"),
        (headline_md(extra=(("speedup", "x", "y", "z"),)), "duplicate headline key: speedup"),
        (
            headline_md({"backend_tests": "<backend test count>"}),
            "unfilled headline value: backend_tests",
        ),
        (headline_md({"eval_verdict": "great"}), "eval_verdict must be one of"),
        (headline_md({"demo_url": "http://example.invalid"}), "demo_url must be an https URL"),
        ("no markers here", "expected exactly one <!-- headline:start -->"),
    ],
    ids=["missing", "unknown", "duplicate", "unfilled", "verdict", "demo-url", "no-block"],
)
def test_parse_headline_rejects_bad_tables(ds: ModuleType, text: str, message: str) -> None:
    with pytest.raises(ds.DocsSyncError, match=re.escape(message)):
        ds.parse_headline(text)


def test_replace_block_rewrites_only_the_block(ds: ModuleType) -> None:
    text = "before\n<!-- x:start -->\nold\n<!-- x:end -->\nafter\n"
    assert ds.block_body(text, "x") == "old"
    assert (
        ds.replace_block(text, "x", "new")
        == "before\n<!-- x:start -->\nnew\n<!-- x:end -->\nafter\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "<!-- x:start -->\n",
        "<!-- x:end -->\n<!-- x:start -->\n",
        "<!-- x:start --><!-- x:start --><!-- x:end -->",
    ],
    ids=["no-end", "reversed", "duplicated"],
)
def test_replace_block_requires_one_ordered_marker_pair(ds: ModuleType, text: str) -> None:
    with pytest.raises(ds.DocsSyncError):
        ds.replace_block(text, "x", "new")


def test_render_rows_rebases_links_onto_the_repository_root(ds: ModuleType) -> None:
    rows = ds.parse_headline(headline_md())
    table = ds.render_rows(
        rows, ("eval_accuracy", "peer_exposure", "mlx_prefill_worker", "demo_url")
    )
    assert table.splitlines()[:2] == ["| Result | Value | Source |", "|---|---|---|"]
    assert "](docs/experiments.md#evaluation)" in table
    assert "](docs/DECISIONS.md#adr-diverse-peer-context)" in table
    assert "](modelfiles/Modelfile.worker)" in table
    assert "](docs/experiments.md#demo)" in table


def test_render_brackets_lists_every_bracket_and_the_total(ds: ModuleType) -> None:
    table = ds.render_brackets(DEFAULT_BRACKETS).splitlines()
    assert len(table) == 2 + len(DEFAULT_BRACKETS) + 1
    for line, bracket in zip(table[2:-1], DEFAULT_BRACKETS, strict=True):
        assert line.startswith(f"| {bracket.display_name} | {bracket.count} | ")
    assert table[-1] == f"| **Total** | **{sum(b.count for b in DEFAULT_BRACKETS)}** | | | |"


def test_bracket_roles_cover_every_bracket_type(ds: ModuleType) -> None:
    assert set(ds.BRACKET_ROLES) == {b.value for b in BracketType}
    assert all("|" not in role for role in ds.BRACKET_ROLES.values())


# ------------------------------------------------------------- captures, resume, release, sync

CAPTURES: dict[str, object] = {
    "cycle_id": "00000000-0000-4000-8000-000000000001",
    "seed_rumor": (
        "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
    ),
    "num_rounds": 3,
    "final_buy": 41,
    "final_sell": 33,
    "final_hold": 26,
    "total_flips": 19,
    "total_seconds": 1854.2,
    "round_seconds": [612.4, 598.1, 571.0],
    "holdings_file": "examples/holdings.example.csv",
    "images": [
        "dashboard-live.png",
        "influence-graph.png",
        "round-story.png",
        "report.png",
        "advisory.png",
    ],
}
README_BLOCKS = ("demo", "runtime", "results", "screenshots", "brackets", "quality")


def _make_root(tmp_path: Path, headline: str) -> Path:
    (tmp_path / "docs" / "media").mkdir(parents=True)
    (tmp_path / "docs" / "experiments.md").write_text(headline, encoding="utf-8")
    (tmp_path / "docs" / "media" / "captures.json").write_text(
        json.dumps(CAPTURES), encoding="utf-8"
    )
    readme = "# README\n" + "".join(
        f"\n<!-- {b}:start -->\n<!-- {b}:end -->\n" for b in README_BLOCKS
    )
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v6.0 (0.6.0) — Unreleased\n\n"
        "<!-- results:start -->\n<!-- results:end -->\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "HISTORY.md").write_text(
        "<!-- resume:start -->\n<!-- resume:end -->\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.6.0"\n', encoding="utf-8"
    )
    return tmp_path


def _rows(ds: ModuleType, **overrides: str) -> dict[str, object]:
    rows: dict[str, object] = ds.parse_headline(headline_md(overrides))
    return rows


def test_resume_quotes_values_with_the_verdict_wording(ds: ModuleType) -> None:
    better = ds.render_resume(_rows(ds), DEFAULT_BRACKETS)
    assert better.count("\n") == 5 and better.startswith("1. Built **AlphaSwarm**")
    assert (
        "it beat the best single-model baseline: hit rate 0.61 (95% CI 0.52-0.70) vs 0.50."
        in better
    )
    assert "(peer-attributable flip rate +6.0 pp (95% CI 2.1 to 9.8))" in better
    assert "cut mean round time from 412 s to 268 s (-35%)" in better
    assert "worker 833 to 2,361 tok/s (2.8x), orchestrator 111 to 3,395 tok/s (30.6x)" in better
    assert "1,512 backend tests (89% coverage) and 412 frontend tests" in better
    assert "a static read-only demo on GitHub Pages" in better
    total = sum(b.count for b in DEFAULT_BRACKETS)
    assert f"runs {total} market personas in {len(DEFAULT_BRACKETS)} archetypes" in better
    flat = ds.render_resume(
        _rows(ds, eval_verdict="no-difference", peer_effect_verdict="null"), DEFAULT_BRACKETS
    )
    assert "showed no significant edge over single-model baselines" in flat
    assert "found no significant peer-attributable flip rate" in flat
    worse = ds.render_resume(
        _rows(ds, eval_verdict="worse", peer_effect_verdict="negative"), DEFAULT_BRACKETS
    )
    assert "trailed the best single-model baseline" in worse
    assert "found that peers reduce flips" in worse


def test_resume_falls_back_when_values_are_not_measured(ds: ModuleType) -> None:
    unmeasured = (
        "eval_accuracy",
        "eval_verdict",
        "peer_effect",
        "peer_effect_verdict",
        "peer_exposure",
        "speedup",
        "mlx_prefill_worker",
        "backend_tests",
        "import_contracts",
    )
    rows = _rows(ds, **{key: "not measured" for key in unmeasured}, demo_url="not published")
    text = ds.render_resume(rows, DEFAULT_BRACKETS)
    assert "not measured" not in text and "not published" not in text
    assert "It ships a point-in-time evaluation harness" in text
    assert "Added a seeded no-peer control group" in text
    assert "hid 6 of 10 brackets from every feed;" in text
    assert "round time" not in text and "benchmarked MLX" not in text
    assert "Raised the quality bar with golden tests" in text
    assert "a static read-only demo build" in text


def test_resume_counts_a_single_import_linter_contract(ds: ModuleType) -> None:
    one = ds.render_resume(_rows(ds, import_contracts="1"), DEFAULT_BRACKETS)
    assert "and 1 import-linter contract;" in one
    assert "and 5 import-linter contracts;" in ds.render_resume(_rows(ds), DEFAULT_BRACKETS)


def test_resume_never_claims_the_github_contribution_graph(ds: ModuleType) -> None:
    assert "contribution" not in ds.render_resume(_rows(ds), DEFAULT_BRACKETS).lower()


def test_render_demo_links_a_published_url_or_explains_the_local_build(ds: ModuleType) -> None:
    assert ds.render_demo(_rows(ds)).startswith("**[Live demo](https://example.invalid/demo/)**")
    assert "VITE_DEMO=1" in ds.render_demo(_rows(ds, demo_url="not published"))


def test_render_screenshots_lists_every_image_and_the_run(ds: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "captures.json"
    path.write_text(json.dumps(CAPTURES), encoding="utf-8")
    text = ds.render_screenshots(ds.load_captures(path))
    for name, alt in ds.IMAGE_SPECS:
        assert f"![{alt}](docs/media/{name})" in text
    assert "cycle `00000000`" in text and "3 rounds in 31 min" in text
    assert "(R1 612 s, R2 598 s, R3 571 s)" in text
    assert "final BUY 41 / SELL 33 / HOLD 26, 19 flips" in text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"holdings_file": "Schwab/holdings.csv"}, "fictional examples/holdings.example.csv"),
        ({"images": ["report.png"]}, "must list exactly"),
        ({"total_seconds": "n/a"}, "malformed"),
        ({"round_seconds": [612.4]}, "one value per round"),
    ],
    ids=["holdings", "images", "malformed", "round-seconds"],
)
def test_load_captures_rejects_bad_files(
    ds: ModuleType, tmp_path: Path, change: dict[str, object], message: str
) -> None:
    path = tmp_path / "captures.json"
    path.write_text(json.dumps({**CAPTURES, **change}), encoding="utf-8")
    with pytest.raises(ds.DocsSyncError, match=re.escape(message)):
        ds.load_captures(path)


EXPORT_METRICS: dict[str, object] = {
    "final_buy": 41,
    "final_sell": 33,
    "final_hold": 26,
    "total_seconds": 1854.2,
    "r1_seconds": 612.4,
    "r2_seconds": 598.1,
    "r3_seconds": 571.0,
    "r2_flips": 12,
    "r3_flips": 7,
}


def _export(*, drop_metric: str = "", **cycle: object) -> str:
    """A minimal `alphaswarm cycles export` document for the captured cycle."""
    meta: dict[str, object] = {
        "cycle_id": CAPTURES["cycle_id"],
        "created_at": "2026-10-20T10:00:00Z",
        "seed_rumor": CAPTURES["seed_rumor"],
        "overall_sentiment": 0.4,
        "num_rounds": 3,
        "status": "complete",
        "metrics": {key: value for key, value in EXPORT_METRICS.items() if key != drop_metric},
        "manifest": None,
    }
    document = {
        "schema": "alphaswarm.cycle-export/1",
        "cycle": {**meta, **cycle},
        "roster": [],
        "rounds": [],
        "report_markdown": None,
        "shocks": [],
    }
    return json.dumps(document)


def test_capture_meta_builds_the_captures_file(ds: ModuleType, tmp_path: Path) -> None:
    meta = ds.capture_meta(_export())
    assert meta == CAPTURES
    path = tmp_path / "captures.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    assert ds.load_captures(path).round_seconds == (612.4, 598.1, 571.0)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (_export(status="running"), "must be complete"),
        (_export(drop_metric="r3_seconds"), "lack r3_seconds"),
        (
            json.dumps({"cycles": [], "next_before": None}),
            "expected an alphaswarm.cycle-export/1 document",
        ),
    ],
    ids=["running", "missing-metric", "not-an-export"],
)
def test_capture_meta_rejects_unusable_exports(ds: ModuleType, raw: str, message: str) -> None:
    with pytest.raises(ds.DocsSyncError, match=re.escape(message)):
        ds.capture_meta(raw)


CHANGELOG_FIXTURE = (
    "# Changelog\n\n"
    "## v6.0 (0.6.0) — 2026-11-02\n\n"
    "Intro with a [link](docs/experiments.md#headline-numbers-v60) and an "
    "[anchor](#v50--2026-04-18).\n\n"
    "<!-- results:start -->\n| Result | Value | Source |\n<!-- results:end -->\n\n"
    "## v5.0 — 2026-04-18\n\nOld entry.\n"
)


def test_release_notes_extract_the_entry_with_absolute_links(ds: ModuleType) -> None:
    notes = ds.release_notes(CHANGELOG_FIXTURE, "v6.0")
    assert notes.startswith(
        "Intro with a [link](https://github.com/Avo-Sarkissian/AlphaSwarm/blob/v6.0/"
        "docs/experiments.md#headline-numbers-v60)"
    )
    assert (
        "[anchor](https://github.com/Avo-Sarkissian/AlphaSwarm/blob/v6.0/CHANGELOG.md#v50--2026-04-18)"
        in notes
    )
    assert "<!--" not in notes and "Old entry" not in notes
    with pytest.raises(ds.DocsSyncError, match="no entry for v7.0"):
        ds.release_notes(CHANGELOG_FIXTURE, "v7.0")


def test_changelog_top_entry_parses_tag_version_and_date(ds: ModuleType) -> None:
    entry = ds.changelog_top_entry(CHANGELOG_FIXTURE)
    assert (entry.tag, entry.version, entry.date) == ("v6.0", "0.6.0", "2026-11-02")
    assert (
        ds.changelog_top_entry(CHANGELOG_FIXTURE.replace("2026-11-02", "Unreleased", 1)).date
        is None
    )
    with pytest.raises(ds.DocsSyncError, match="malformed"):
        ds.changelog_top_entry("## v6.0 - soon\n")


def test_release_problems_flag_unmeasured_values_and_an_undated_changelog(
    ds: ModuleType, tmp_path: Path
) -> None:
    root = _make_root(
        tmp_path, headline_md({"speedup": "not measured", "demo_url": "not published"})
    )
    assert ds.release_problems(root) == [
        "headline value not measured: speedup",
        "the top CHANGELOG entry is still 'Unreleased'",
    ]


def test_sync_reports_then_writes_stale_blocks(ds: ModuleType, tmp_path: Path) -> None:
    root = _make_root(tmp_path, headline_md())
    stale = ds.sync(root, DEFAULT_BRACKETS, write=False)
    assert sorted(stale) == sorted(
        [f"README.md:{block}" for block in README_BLOCKS]
        + ["CHANGELOG.md:results", "docs/HISTORY.md:resume"]
    )
    assert ds.sync(root, DEFAULT_BRACKETS, write=True) == stale
    assert ds.sync(root, DEFAULT_BRACKETS, write=False) == []
    assert "| Swarm accuracy vs the best baseline |" in (root / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )


def test_sync_skips_a_missing_changelog(ds: ModuleType, tmp_path: Path) -> None:
    root = _make_root(tmp_path, headline_md())
    (root / "CHANGELOG.md").unlink()
    assert "CHANGELOG.md:results" not in ds.sync(root, DEFAULT_BRACKETS, write=True)
    assert ds.sync(root, DEFAULT_BRACKETS, write=False) == []
    with pytest.raises(ds.DocsSyncError, match="CHANGELOG.md is missing"):
        ds.release_problems(root)


def test_main_check_exit_codes(
    ds: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_root(tmp_path, headline_md())
    assert ds.main(["--root", str(root), "check"]) == 1
    assert "run: uv run python scripts/docs_sync.py write" in capsys.readouterr().err
    assert ds.main(["--root", str(root), "write"]) == 0
    assert ds.main(["--root", str(root), "check"]) == 0
    (root / "docs" / "experiments.md").write_text(headline_md(drop=("demo_url",)), encoding="utf-8")
    assert ds.main(["--root", str(root), "check"]) == 2


@pytest.mark.parametrize("missing", ["docs/experiments.md", "README.md", "docs/HISTORY.md"])
def test_main_reports_a_missing_source_as_malformed(
    ds: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    root = _make_root(tmp_path, headline_md())
    (root / missing).unlink()
    assert ds.main(["--root", str(root), "check"]) == 2
    assert f"docs_sync: missing {missing}" in capsys.readouterr().err
