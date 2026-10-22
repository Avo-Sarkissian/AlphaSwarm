"""scripts/docs_sync.py renders the generated Markdown blocks from code and results."""

from __future__ import annotations

import re
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
            headline_md({"backend_tests": "<Task 9 Step 4>"}),
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
