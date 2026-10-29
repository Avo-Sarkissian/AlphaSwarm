"""Render the generated Markdown blocks from the code and the measured results.

A generated block sits between ``<!-- NAME:start -->`` and ``<!-- NAME:end -->``.
Sources: ``DEFAULT_BRACKETS`` (bracket table), the headline table in
``docs/experiments.md`` (results, quality, run time, demo link, CHANGELOG results,
resume bullets) and ``docs/media/captures.json`` (screenshot gallery). The demo line
and the resume bullets name a feature only when ``repo_facts`` finds it in the
repository. Rationale: docs/DECISIONS.md#adr-docs-sync.

    uv run python scripts/docs_sync.py check [--release]
    uv run python scripts/docs_sync.py write
    uv run python scripts/docs_sync.py release-notes v6.0
    uv run python scripts/docs_sync.py capture-meta < cycle-export.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.types import BracketConfig

ROOT: Final = Path(__file__).resolve().parents[1]
EXPERIMENTS: Final = "docs/experiments.md"
CAPTURES: Final = "docs/media/captures.json"
REPO_BLOB: Final = "https://github.com/Avo-Sarkissian/AlphaSwarm/blob"
EXAMPLE_HOLDINGS: Final = "examples/holdings.example.csv"
EXPORT_SCHEMA: Final = "alphaswarm.cycle-export/1"
NOT_MEASURED: Final = "not measured"
NOT_PUBLISHED: Final = "not published"
CI_WORKFLOW: Final = ".github/workflows/ci.yml"
METHODOLOGY: Final = "docs/methodology.md"
FRONTEND_CODE_SUFFIXES: Final = frozenset({".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"})

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
    "eval_verdict": frozenset({"better", "inconclusive", "worse", NOT_MEASURED}),
    "peer_effect_verdict": frozenset({"positive", "null", "negative", NOT_MEASURED}),
}
RELEASE_OPTIONAL: Final = frozenset({"demo_url"})
OPTIONAL_TARGETS: Final = frozenset({"CHANGELOG.md"})  # created late in the release work

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
IMAGE_SPECS: Final[tuple[tuple[str, str], ...]] = (
    (
        "dashboard-live.png",
        "Live dashboard during Round 2: agents fill in as they decide, dim dots are still thinking",
    ),
    (
        "influence-graph.png",
        "Influence graph after the final round with one agent focused: arrows run from the "
        "cited agent to the citing agent",
    ),
    (
        "round-story.png",
        "Replay with the round scrubber: rings mark the agents that flipped since the "
        "previous round",
    ),
    ("report.png", "Cycle report: round-by-round convergence, influence leaders and dissent"),
    (
        "advisory.png",
        "Advisory on the fictional example holdings, under the not-investment-advice banner",
    ),
)

TOP_ENTRY: Final = re.compile(
    r"^## (?P<tag>v\d\S*) \((?P<version>\d+\.\d+\.\d+)\) — "
    r"(?P<date>Unreleased|\d{4}-\d{2}-\d{2})$"
)
_LINK_TARGET: Final = re.compile(r"\]\(([^)\s]+)\)")
_SCHEME: Final = re.compile(r"^[a-z][a-z0-9+.-]*:")
_BLOCK_MARKER: Final = re.compile(r"^<!-- [a-z_]+:(?:start|end) -->$")


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


@dataclass(frozen=True)
class Captures:
    cycle_id: str
    seed_rumor: str
    num_rounds: int
    final_buy: int
    final_sell: int
    final_hold: int
    total_flips: int
    total_seconds: float
    round_seconds: tuple[float, ...]
    holdings_file: str
    images: tuple[str, ...]


@dataclass(frozen=True)
class ChangelogEntry:
    tag: str
    version: str
    date: str | None  # None while the entry is "Unreleased"


@dataclass(frozen=True)
class RepoFacts:
    """Features the demo line and the resume bullets may name, read from the repository.

    A sentence about a feature appears only once the feature exists, so ``write`` never
    publishes a claim ahead of the code (docs/DECISIONS.md#adr-docs-sync).
    """

    demo_build: bool  # the frontend reads VITE_DEMO, so the static demo can be built
    run_manifest: bool  # alphaswarm.manifest defines RunManifest
    preregistered: bool  # docs/methodology.md, which pre-registers the metrics, exists
    call_telemetry: bool  # alphaswarm.inference.call_log logs every inference call
    ruff_gated: bool  # a CI workflow step runs ruff check


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


def _read(root: Path, rel: str) -> str:
    """Read a source or target file; a missing one is malformed input, not a stale block."""
    try:
        return (root / rel).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DocsSyncError(f"missing {rel}") from exc


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


# --------------------------------------------------------------------------- repository facts


def _text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _frontend_reads(root: Path, name: str) -> bool:
    frontend = root / "frontend"
    candidates = [*frontend.glob("vite.config.*"), *(frontend / "src").rglob("*")]
    return any(
        path.suffix in FRONTEND_CODE_SUFFIXES and path.is_file() and name in _text_or_empty(path)
        for path in candidates
    )


def repo_facts(root: Path) -> RepoFacts:
    ci_lines = [
        line
        for line in _text_or_empty(root / CI_WORKFLOW).splitlines()
        if not line.lstrip().startswith("#")
    ]
    package = root / "src" / "alphaswarm"
    return RepoFacts(
        demo_build=_frontend_reads(root, "VITE_DEMO"),
        run_manifest="class RunManifest" in _text_or_empty(package / "manifest.py"),
        preregistered=(root / METHODOLOGY).is_file(),
        call_telemetry=(package / "inference" / "call_log.py").is_file(),
        ruff_gated=any("ruff check" in line for line in ci_lines),
    )


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


def render_demo(rows: Mapping[str, HeadlineRow], *, facts: RepoFacts | None = None) -> str:
    """The README demo line; without ``facts`` it follows this repository's features."""
    url = rows["demo_url"].value
    if url.startswith("https://"):
        return (
            f"**[Live demo]({url})**: a read-only replay of one cycle in your browser, "
            "no install needed."
        )
    if not (repo_facts(ROOT) if facts is None else facts).demo_build:
        return ""  # nothing published and nothing to build: the README names no demo
    return (
        "**Demo:** a static, read-only replay of one cycle, available once published. Until "
        "then, build it locally with "
        "`VITE_DEMO=1 npm --prefix frontend run build && npm --prefix frontend run preview`."
    )


def load_captures(path: Path) -> Captures:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        captures = Captures(
            cycle_id=str(data["cycle_id"]),
            seed_rumor=str(data["seed_rumor"]),
            num_rounds=int(data["num_rounds"]),
            final_buy=int(data["final_buy"]),
            final_sell=int(data["final_sell"]),
            final_hold=int(data["final_hold"]),
            total_flips=int(data["total_flips"]),
            total_seconds=float(data["total_seconds"]),
            round_seconds=tuple(float(s) for s in data["round_seconds"]),
            holdings_file=str(data["holdings_file"]),
            images=tuple(str(name) for name in data["images"]),
        )
    except FileNotFoundError as exc:
        raise DocsSyncError(f"missing {CAPTURES}; run the capture step first") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise DocsSyncError(f"malformed {CAPTURES}: {exc!r}") from exc
    if len(captures.round_seconds) != captures.num_rounds:
        raise DocsSyncError(f"{CAPTURES} round_seconds must have one value per round")
    if captures.holdings_file != EXAMPLE_HOLDINGS:
        raise DocsSyncError(f"captures must use the fictional {EXAMPLE_HOLDINGS}")
    expected = tuple(name for name, _ in IMAGE_SPECS)
    if captures.images != expected:
        raise DocsSyncError(f"{CAPTURES} must list exactly {list(expected)}")
    return captures


def render_screenshots(captures: Captures) -> str:
    (first, first_alt), *rest = IMAGE_SPECS
    out = ["### Screenshots", "", f"![{first_alt}](docs/media/{first})", "", f"*{first_alt}.*"]
    out += ["", "| | |", "|---|---|"]
    for (left, left_alt), (right, right_alt) in zip(rest[0::2], rest[1::2], strict=True):
        out.append(f"| ![{left_alt}](docs/media/{left}) | ![{right_alt}](docs/media/{right}) |")
        out.append(f"| *{left_alt}.* | *{right_alt}.* |")
    minutes = round(captures.total_seconds / 60)
    per_round = ", ".join(
        f"R{n} {seconds:.0f} s" for n, seconds in enumerate(captures.round_seconds, start=1)
    )
    out += [
        "",
        f"All five captures come from one real run: cycle `{captures.cycle_id[:8]}`, seed "
        f'"{captures.seed_rumor}", {captures.num_rounds} rounds in {minutes} min '
        f"({per_round}), final BUY {captures.final_buy} / SELL {captures.final_sell} / "
        f"HOLD {captures.final_hold}, {captures.total_flips} flips. The advisory used the "
        f"fictional `{captures.holdings_file}`.",
    ]
    return "\n".join(out)


def _measured(rows: Mapping[str, HeadlineRow], key: str) -> str | None:
    row = rows[key]
    return row.value if row.measured else None


def _resume_project(
    rows: Mapping[str, HeadlineRow], agents: int, brackets: int, facts: RepoFacts
) -> str:
    base = (
        "Built **AlphaSwarm**, a local-first multi-agent LLM simulation engine (Python 3.11 "
        f"asyncio, FastAPI, Neo4j, Ollama on MLX) that runs {agents} market personas in "
        f"{brackets} archetypes through a multi-round consensus cascade and streams it to a "
        "live influence graph."
    )
    registered = " with pre-registered metrics" if facts.preregistered else ""
    accuracy, verdict = _measured(rows, "eval_accuracy"), rows["eval_verdict"].value
    if accuracy is None or verdict == NOT_MEASURED:
        metrics = "pre-registered metrics and " if facts.preregistered else ""
        return base + (
            f" It ships a point-in-time evaluation harness with {metrics}single-model baselines."
        )
    if verdict == "better":
        return base + (
            " On a point-in-time evaluation against real outcomes it beat the best "
            f"single-model baseline: {accuracy}."
        )
    if verdict == "worse":
        return base + (
            " On a point-in-time evaluation against real outcomes it trailed the best "
            f"single-model baseline ({accuracy}), reported as measured{registered}."
        )
    if facts.run_manifest:  # the reproduction claim needs stored manifests, as in _resume_method
        harness = "pre-registered harness" if facts.preregistered else "harness"
        tail = f"a result the {harness} reproduces from stored run manifests"
    else:
        tail = f"reported as measured{registered}"
    return base + (
        " On a point-in-time evaluation against real outcomes it showed no significant edge over "
        f"single-model baselines ({accuracy}), {tail}."
    )


def _resume_method(rows: Mapping[str, HeadlineRow], facts: RepoFacts) -> str:
    effect, verdict = _measured(rows, "peer_effect"), rows["peer_effect_verdict"].value
    if effect is None or verdict == NOT_MEASURED:
        lead = "Added a seeded no-peer control group to separate peer influence from noise"
    elif verdict == "positive":
        lead = (
            "Turned round-to-round opinion flips into a measured effect with a seeded no-peer "
            f"control group (peer-attributable flip rate {effect})"
        )
    elif verdict == "negative":
        lead = (
            "Tested peer influence against a seeded no-peer control group and found that "
            f"peers reduce flips ({effect})"
        )
    else:
        lead = (
            "Tested whether peers move opinions with a seeded no-peer control group and found no "
            f"significant peer-attributable flip rate ({effect})"
        )
    exposure = _measured(rows, "peer_exposure")
    fix = "after fixing a peer-selection bias that hid 6 of 10 brackets from every feed"
    if exposure is not None:
        fix += f" ({exposure})"
    if not facts.run_manifest:
        return f"{lead}, {fix}."
    return (
        f"{lead}, {fix}; every run stores a manifest (seeds, model digests, prompt hashes) "
        "so any run can be traced and re-run."
    )


def _resume_performance(rows: Mapping[str, HeadlineRow], facts: RepoFacts) -> str:
    text = (
        "Designed a memory-aware concurrency governor for a 64 GB M1 Max (macOS kernel memory "
        "signal, crisis escalation, gradual recovery)"
    )
    if facts.call_telemetry:
        text += " and per-call inference telemetry"
    speedup = _measured(rows, "speedup")
    if speedup is not None:
        changes = "telemetry-driven changes" if facts.call_telemetry else "performance changes"
        text += f"; {changes} cut mean round time {speedup}"
    worker = _measured(rows, "mlx_prefill_worker")
    orchestrator = _measured(rows, "mlx_prefill_orchestrator")
    if worker is not None and orchestrator is not None:
        text += f"; benchmarked MLX prefill: worker {worker}, orchestrator {orchestrator}"
    return text + "."


def _resume_ui(rows: Mapping[str, HeadlineRow], facts: RepoFacts) -> str:
    dashboard = (
        "Built a real-time React/TypeScript dashboard on a versioned 5 Hz WebSocket contract "
        "with latest-wins backpressure"
    )
    graph = "a deterministic influence graph that replays the round-by-round citation cascade"
    if rows["demo_url"].value.startswith("https://"):
        return f"{dashboard}, {graph}, and a static read-only demo on GitHub Pages."
    if facts.demo_build:
        return f"{dashboard}, {graph}, and a static read-only demo build."
    return f"{dashboard}, and {graph}."


_RESUME_PRIVACY: Final = (
    "Delivered a privacy-isolated portfolio advisory: holdings never reach agent prompts, "
    "Neo4j, WebSocket frames or logs, which an import-linter contract and a four-surface "
    "canary test enforce, and no ticker reaches a cloud model without an explicit opt-in."
)


def _resume_quality(rows: Mapping[str, HeadlineRow], facts: RepoFacts) -> str:
    tests = _measured(rows, "backend_tests")
    coverage = _measured(rows, "backend_coverage")
    frontend = _measured(rows, "frontend_tests")
    contracts = _measured(rows, "import_contracts")
    if contracts is None:
        imports = "import-linter contracts"
    else:
        imports = f"{contracts} import-linter contract{'' if contracts == '1' else 's'}"
    linters = "mypy strict, ruff, ESLint" if facts.ruff_gated else "mypy strict, ESLint"
    gates = f"gated {linters} and {imports}"
    if tests is not None and coverage is not None and frontend is not None:
        lead = (
            f"Raised the quality bar to {tests} backend tests ({coverage} coverage) and {frontend} "
            f"frontend tests, with golden tests against a throwaway Neo4j in CI and {gates}"
        )
    else:
        lead = (
            f"Raised the quality bar with golden tests against a throwaway Neo4j in CI and {gates}"
        )
    return lead + "; fixed 35 audit findings and 6 security-scan issues with regression tests."


# Bullet number, the headline keys whose result it would quote, and what it waits on.
_RESUME_PENDING: Final[tuple[tuple[int, tuple[str, ...], str], ...]] = (
    (1, ("eval_accuracy", "eval_verdict"), "the evaluation runs against real outcomes"),
    (2, ("peer_effect", "peer_effect_verdict"), "the control-group runs"),
    (3, ("speedup",), "the performance-arm runs"),
    (6, ("backend_tests", "backend_coverage", "frontend_tests"), "a test-suite count"),
)


def _resume_placeholders(rows: Mapping[str, HeadlineRow]) -> str:
    """A note naming the bullets that leave out a result because it is not measured yet."""
    waiting = [
        f"bullet {number} waits on {what}"
        for number, keys, what in _RESUME_PENDING
        if any(not rows[key].measured for key in keys)
    ]
    if not waiting:
        return ""
    return (
        f"**Placeholders:** {'; '.join(waiting)}. Until then each of these bullets says what "
        "the code does, without a result."
    )


def render_resume(
    rows: Mapping[str, HeadlineRow],
    brackets: Sequence[BracketConfig],
    *,
    facts: RepoFacts | None = None,
) -> str:
    """Six numbered bullets, then a note on the bullets still waiting for a measurement.

    Without ``facts`` they follow this repository's features.
    """
    present = repo_facts(ROOT) if facts is None else facts
    bullets = (
        _resume_project(rows, sum(b.count for b in brackets), len(brackets), present),
        _resume_method(rows, present),
        _resume_performance(rows, present),
        _resume_ui(rows, present),
        _RESUME_PRIVACY,
        _resume_quality(rows, present),
    )
    text = "\n".join(f"{n}. {bullet}" for n, bullet in enumerate(bullets, start=1))
    note = _resume_placeholders(rows)
    return f"{text}\n\n{note}" if note else text


# --------------------------------------------------------------------------- sync


def expected_blocks(root: Path, brackets: Sequence[BracketConfig]) -> dict[tuple[str, str], str]:
    rows = parse_headline(_read(root, EXPERIMENTS))
    facts = repo_facts(root)
    results = render_rows(rows, RESULT_KEYS)
    # No gallery until the capture run writes captures.json: the README shows no screenshot
    # that does not exist (docs/DECISIONS.md#adr-docs-sync).
    captures = root / CAPTURES
    gallery = render_screenshots(load_captures(captures)) if captures.exists() else ""
    return {
        ("README.md", "demo"): render_demo(rows, facts=facts),
        ("README.md", "runtime"): render_rows(rows, RUNTIME_KEYS),
        ("README.md", "results"): results,
        ("README.md", "screenshots"): gallery,
        ("README.md", "brackets"): render_brackets(brackets),
        ("README.md", "quality"): render_rows(rows, QUALITY_KEYS),
        ("CHANGELOG.md", "results"): results,
        ("docs/HISTORY.md", "resume"): render_resume(rows, brackets, facts=facts),
    }


def sync(root: Path, brackets: Sequence[BracketConfig], *, write: bool) -> list[str]:
    """Return the stale blocks as "path:block"; with write=True also rewrite them."""
    texts: dict[str, str] = {}
    stale: list[str] = []
    for (rel, name), body in expected_blocks(root, brackets).items():
        path = root / rel
        if rel in OPTIONAL_TARGETS and not path.exists():
            continue
        text = texts.get(rel)
        if text is None:
            text = _read(root, rel)
        if block_body(text, name) != body.strip("\n"):
            stale.append(f"{rel}:{name}")
            text = replace_block(text, name, body)
        texts[rel] = text
    if write:
        for rel in sorted({entry.split(":", 1)[0] for entry in stale}):
            (root / rel).write_text(texts[rel], encoding="utf-8")
    return stale


# --------------------------------------------------------------------------- release


def changelog_top_entry(changelog_md: str) -> ChangelogEntry:
    for line in changelog_md.splitlines():
        if line.startswith("## "):
            match = TOP_ENTRY.match(line)
            if match is None:
                raise DocsSyncError(f"the top CHANGELOG entry is malformed: {line!r}")
            date = match.group("date")
            return ChangelogEntry(
                tag=match.group("tag"),
                version=match.group("version"),
                date=None if date == "Unreleased" else date,
            )
    raise DocsSyncError("CHANGELOG.md has no entries")


def release_notes(changelog_md: str, tag: str) -> str:
    lines = changelog_md.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"## {tag} ")), None)
    if start is None:
        raise DocsSyncError(f"CHANGELOG.md has no entry for {tag}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(ln for ln in lines[start + 1 : end] if not _BLOCK_MARKER.match(ln)).strip()

    def absolute(target: str) -> str:
        if _SCHEME.match(target):
            return target
        if target.startswith("#"):  # a release page has no CHANGELOG headings to jump to
            return f"{REPO_BLOB}/{tag}/CHANGELOG.md{target}"
        return f"{REPO_BLOB}/{tag}/{target}"

    return _rewrite_links(body, absolute) + "\n"


def release_problems(root: Path) -> list[str]:
    rows = parse_headline(_read(root, EXPERIMENTS))
    problems = [
        f"headline value not measured: {key}"
        for key in HEADLINE_KEYS
        if key not in RELEASE_OPTIONAL and rows[key].value == NOT_MEASURED
    ]
    with (root / "pyproject.toml").open("rb") as handle:
        version = str(tomllib.load(handle)["project"]["version"])
    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DocsSyncError("CHANGELOG.md is missing") from exc
    entry = changelog_top_entry(changelog)
    if entry.version != version:
        problems.append(
            f"the top CHANGELOG entry is {entry.version}; pyproject.toml says {version}"
        )
    if entry.date is None:
        problems.append("the top CHANGELOG entry is still 'Unreleased'")
    return problems


def capture_meta(export_json: str) -> dict[str, object]:
    """Build docs/media/captures.json from the output of `alphaswarm cycles export CYCLE_ID`."""
    payload = json.loads(export_json)
    if not isinstance(payload, dict) or payload.get("schema") != EXPORT_SCHEMA:
        raise DocsSyncError(f"expected an {EXPORT_SCHEMA} document from `alphaswarm cycles export`")
    cycle = payload.get("cycle")
    metrics = cycle.get("metrics") if isinstance(cycle, dict) else None
    if not isinstance(cycle, dict) or not isinstance(metrics, dict):
        raise DocsSyncError("the export has no cycle metrics")
    if cycle.get("status") != "complete":
        raise DocsSyncError("the captured cycle must be complete")
    rounds = cycle.get("num_rounds")
    if not isinstance(rounds, int) or rounds < 1:
        raise DocsSyncError("the export has no num_rounds")
    needed = ["final_buy", "final_sell", "final_hold", "total_seconds"]
    needed += [f"r{n}_seconds" for n in range(1, rounds + 1)]
    needed += [f"r{n}_flips" for n in range(2, rounds + 1)]
    absent = [key for key in needed if metrics.get(key) is None]
    if absent:
        raise DocsSyncError(f"the cycle metrics lack {', '.join(absent)}")
    return {
        "cycle_id": cycle["cycle_id"],
        "seed_rumor": cycle["seed_rumor"],
        "num_rounds": rounds,
        "final_buy": metrics["final_buy"],
        "final_sell": metrics["final_sell"],
        "final_hold": metrics["final_hold"],
        "total_flips": sum(int(metrics[f"r{n}_flips"]) for n in range(2, rounds + 1)),
        "total_seconds": metrics["total_seconds"],
        "round_seconds": [metrics[f"r{n}_seconds"] for n in range(1, rounds + 1)],
        "holdings_file": EXAMPLE_HOLDINGS,
        "images": [name for name, _ in IMAGE_SPECS],
    }


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docs_sync.py", description="Keep the generated Markdown blocks in sync."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="exit 1 when a generated block is stale")
    check.add_argument("--release", action="store_true", help="also require release-ready values")
    sub.add_parser("write", help="rewrite the stale generated blocks")
    notes = sub.add_parser("release-notes", help="print a CHANGELOG entry with absolute links")
    notes.add_argument("tag")
    sub.add_parser(
        "capture-meta", help="captures.json from `alphaswarm cycles export` JSON on stdin"
    )
    args = parser.parse_args(argv)
    root: Path = args.root
    try:
        if args.command == "release-notes":
            changelog = _read(root, "CHANGELOG.md")
            sys.stdout.write(release_notes(changelog, args.tag))
            return 0
        if args.command == "capture-meta":
            print(json.dumps(capture_meta(sys.stdin.read()), indent=2))
            return 0
        stale = sync(root, DEFAULT_BRACKETS, write=args.command == "write")
        if args.command == "write":
            print("updated: " + ", ".join(stale) if stale else "all generated blocks are current")
            return 0
        problems = [f"stale block: {entry}" for entry in stale]
        if args.release:
            problems += release_problems(root)
        for problem in problems:
            print(problem, file=sys.stderr)
        if stale:
            print("run: uv run python scripts/docs_sync.py write", file=sys.stderr)
        return 1 if problems else 0
    except DocsSyncError as exc:
        print(f"docs_sync: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
