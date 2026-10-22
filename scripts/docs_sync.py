"""Render the generated Markdown blocks from the code and the measured results.

A generated block sits between ``<!-- NAME:start -->`` and ``<!-- NAME:end -->``.
Sources: ``DEFAULT_BRACKETS`` (bracket table), the headline table in
``docs/experiments.md`` (results, quality, run time, demo link, CHANGELOG results,
resume bullets) and ``docs/media/captures.json`` (screenshot gallery).
Rationale: docs/DECISIONS.md#adr-docs-sync.

    uv run python scripts/docs_sync.py check [--release]
    uv run python scripts/docs_sync.py write
    uv run python scripts/docs_sync.py release-notes v6.0
    uv run python scripts/docs_sync.py capture-meta < cycle-export.json
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphaswarm.types import BracketConfig

ROOT: Final = Path(__file__).resolve().parents[1]
EXPERIMENTS: Final = "docs/experiments.md"
NOT_MEASURED: Final = "not measured"
NOT_PUBLISHED: Final = "not published"

HEADLINE_HEADER: Final = ("Key", "Result", "Value", "Source")
HEADLINE_KEYS: Final[tuple[str, ...]] = (
    "eval_accuracy",
    "eval_verdict",
    "peer_effect",
    "peer_effect_verdict",
    "ablation_rounds",
    "ablation_peers",
    "peer_exposure",
    "speedup",
    "mlx_prefill_worker",
    "mlx_prefill_orchestrator",
    "model_weights",
    "wall_clock_3r",
    "wall_clock_2r",
    "backend_tests",
    "backend_coverage",
    "frontend_tests",
    "import_contracts",
    "demo_url",
)
RESULT_KEYS: Final = (
    "eval_accuracy",
    "peer_effect",
    "ablation_rounds",
    "ablation_peers",
    "peer_exposure",
    "speedup",
    "mlx_prefill_worker",
    "mlx_prefill_orchestrator",
)
RUNTIME_KEYS: Final = ("model_weights", "wall_clock_3r", "wall_clock_2r")
QUALITY_KEYS: Final = ("backend_tests", "backend_coverage", "frontend_tests", "import_contracts")
VERDICTS: Final[Mapping[str, frozenset[str]]] = {
    "eval_verdict": frozenset({"better", "no-difference", "worse", NOT_MEASURED}),
    "peer_effect_verdict": frozenset({"positive", "null", "negative", NOT_MEASURED}),
}

BRACKET_ROLES: Final[Mapping[str, str]] = {
    "institutions": "Benchmark-bound buy-side managers; act on corroborated news, default to HOLD",
    "sell_side": "Research analysts who frame the story; lean BUY or HOLD and move fast",
    "event_driven": "Merger-arb and catalyst funds; price the odds that the event happens",
    "quants": "Statistical models over narrative; HOLD without significant data",
    "degens": "Leveraged retail momentum traders; rarely HOLD",
    "narrators": "Media and FinTwit voices; amplify the winning story, hold no positions",
    "algos": "Systematic strategies; trade only on measurable signals",
    "macro": "Rates, policy and cross-asset regimes; reason about second-order effects",
    "shorts": "Forensic short sellers; lean SELL on hype",
    "allocators": "Decades-horizon capital; rebalance against crowd extremes",
}

_LINK_TARGET: Final = re.compile(r"\]\(([^)\s]+)\)")
_SCHEME: Final = re.compile(r"^[a-z][a-z0-9+.-]*:")


class DocsSyncError(Exception):
    """A source table, the captures file or a target block is malformed."""


@dataclass(frozen=True)
class HeadlineRow:
    key: str
    label: str
    value: str
    source: str

    @property
    def measured(self) -> bool:
        return self.value not in {NOT_MEASURED, NOT_PUBLISHED}


# --------------------------------------------------------------------------- blocks


def _span(text: str, name: str) -> tuple[int, int]:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise DocsSyncError(f"expected exactly one {start} and one {end}")
    i, j = text.index(start), text.index(end)
    if j < i:
        raise DocsSyncError(f"{end} comes before {start}")
    return i + len(start), j


def block_body(text: str, name: str) -> str:
    i, j = _span(text, name)
    return text[i:j].strip("\n")


def replace_block(text: str, name: str, body: str) -> str:
    i, j = _span(text, name)
    return text[:i] + "\n" + body.strip("\n") + "\n" + text[j:]


# --------------------------------------------------------------------------- headline table


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        raise DocsSyncError(f"not a table row: {line!r}")
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def parse_headline(experiments_md: str) -> dict[str, HeadlineRow]:
    lines = [ln for ln in block_body(experiments_md, "headline").splitlines() if ln.strip()]
    if len(lines) < 2 or tuple(_cells(lines[0])) != HEADLINE_HEADER:
        raise DocsSyncError("the headline block must start with | Key | Result | Value | Source |")
    rows: dict[str, HeadlineRow] = {}
    for line in lines[2:]:
        cells = _cells(line)
        if len(cells) != len(HEADLINE_HEADER):
            raise DocsSyncError(f"expected 4 cells, got {len(cells)}: {line!r}")
        key, label, value, source = cells
        key = key.strip("`")
        if key not in HEADLINE_KEYS:
            raise DocsSyncError(f"unknown headline key: {key}")
        if key in rows:
            raise DocsSyncError(f"duplicate headline key: {key}")
        if not value or (value.startswith("<") and value.endswith(">")):
            raise DocsSyncError(f"unfilled headline value: {key}")
        allowed = VERDICTS.get(key)
        if allowed is not None and value not in allowed:
            raise DocsSyncError(f"{key} must be one of {sorted(allowed)}, got {value!r}")
        if key == "demo_url" and value != NOT_PUBLISHED and not value.startswith("https://"):
            raise DocsSyncError(f"demo_url must be an https URL or {NOT_PUBLISHED!r}")
        rows[key] = HeadlineRow(key=key, label=label, value=value, source=source)
    missing = [key for key in HEADLINE_KEYS if key not in rows]
    if missing:
        raise DocsSyncError(f"the headline table is missing keys: {', '.join(missing)}")
    return rows


# --------------------------------------------------------------------------- links


def _rewrite_links(text: str, rewrite: Callable[[str], str]) -> str:
    return _LINK_TARGET.sub(lambda m: "](" + rewrite(m.group(1)) + ")", text)


def _docs_to_root(target: str) -> str:
    """Rebase a link written inside docs/experiments.md onto the repository root."""
    if _SCHEME.match(target):
        return target
    if target.startswith("#"):
        return EXPERIMENTS + target
    if target.startswith("../"):
        return target[3:]
    return "docs/" + target


# --------------------------------------------------------------------------- renderers


def render_rows(rows: Mapping[str, HeadlineRow], keys: Sequence[str]) -> str:
    out = ["| Result | Value | Source |", "|---|---|---|"]
    for key in keys:
        row = rows[key]
        value = _rewrite_links(row.value, _docs_to_root)
        source = _rewrite_links(row.source, _docs_to_root)
        out.append(f"| {row.label} | {value} | {source} |")
    return "\n".join(out)


def render_brackets(brackets: Sequence[BracketConfig]) -> str:
    drift = {b.bracket_type.value for b in brackets} ^ set(BRACKET_ROLES)
    if drift:
        raise DocsSyncError(f"BRACKET_ROLES and DEFAULT_BRACKETS disagree on {sorted(drift)}")
    out = [
        "| Bracket | Agents | Reach weight | Temperature | Role |",
        "|---|---:|---:|---:|---|",
    ]
    for b in brackets:
        out.append(
            f"| {b.display_name} | {b.count} | {b.influence_weight_base:.2f} | "
            f"{b.temperature:.2f} | {BRACKET_ROLES[b.bracket_type.value]} |"
        )
    out.append(f"| **Total** | **{sum(b.count for b in brackets)}** | | | |")
    return "\n".join(out)
