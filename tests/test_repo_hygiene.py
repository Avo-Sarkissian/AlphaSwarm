"""Repository hygiene invariants from Phase 0.

Pins the GSD retirement (T12.10, T9.8 step 1) and, as later tasks extend this
file, iCloud-copy protection (T12.8), ignore rules (T7.7, T12.11), archived
leftovers and attribution (T12.6). Code comments must cite
docs/DECISIONS.md anchors, and every anchor cited must exist. The docs may
cite only commits reachable from HEAD, and until plan 02 replaces the live
Neo4j fixtures, no second test module may request them.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "DECISIONS.md"
CODE_DIRS: tuple[str, ...] = ("src", "tests", "frontend/src", "scripts", "modelfiles")
PLANNING_DIR = "." + "planning"  # built so this file never contains the literal path
_ANCHOR_CITE = re.compile(r"DECISIONS\.md#([a-z0-9][a-z0-9-]*)")
_LEGACY_ID = re.compile(r"\b(?:KR-\d+(?:\.\d+)*-\d+|D-\d{2}|F-\d{2})\b")

pytestmark = pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout (git ls-files)")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def _tracked(*paths: str) -> list[str]:
    result = _git("ls-files", "--", *paths)
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


# --------- GSD retirement (T12.10, T9.8 step 1) ---------


def test_no_planning_directory_is_tracked() -> None:
    assert _tracked(PLANNING_DIR) == []


def test_code_does_not_cite_planning_paths() -> None:
    needle = PLANNING_DIR + "/"
    offenders = [rel for rel in _tracked(*CODE_DIRS) if needle in _read(rel)]
    assert offenders == []


def test_cited_decision_anchors_resolve() -> None:
    defined = set(re.findall(r'<a id="([^"]+)"', DECISIONS.read_text(encoding="utf-8")))
    cited: dict[str, str] = {}
    for rel in _tracked(*CODE_DIRS, "CLAUDE.md", "README.md", "docs"):
        for anchor in _ANCHOR_CITE.findall(_read(rel)):
            cited.setdefault(anchor, rel)
    missing = {anchor: rel for anchor, rel in cited.items() if anchor not in defined}
    assert missing == {}


def test_legacy_ids_cited_in_code_are_indexed() -> None:
    index = DECISIONS.read_text(encoding="utf-8")
    cited = {match for rel in _tracked(*CODE_DIRS) for match in _LEGACY_ID.findall(_read(rel))}
    assert sorted(legacy for legacy in cited if legacy not in index) == []


def test_agents_md_is_a_symlink_to_claude_md() -> None:
    agents = ROOT / "AGENTS.md"
    assert agents.is_symlink()
    assert agents.readlink() == Path("CLAUDE.md")


def test_claude_md_has_no_gsd_workflow() -> None:
    assert "gsd" not in _read("CLAUDE.md").lower()


# --------- Commit SHAs cited in docs (history rewrites: Task 4 R1, gate G-02 B) ---------

_HEX_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")


def test_commit_shas_cited_in_docs_are_in_history() -> None:
    """Every commit SHA the Markdown docs cite must be reachable from HEAD.

    Rewriting commits changes their SHAs, so the docs that cite them must be
    repointed in the same change. Tokens that are not commits in this object
    store (other hashes, or history that a shallow CI clone lacks) are skipped.
    """
    cited: dict[str, str] = {}
    for rel in _tracked("docs", "CLAUDE.md", "README.md"):
        if rel.endswith(".md"):
            for token in _HEX_TOKEN.findall(_read(rel)):
                cited.setdefault(token, rel)
    batch = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=ROOT,
        input="".join(f"{token}\n" for token in cited),
        capture_output=True,
        text=True,
        check=True,
    )
    reachable = set(_git("rev-list", "HEAD").stdout.split())
    stale = [
        f"{cited[token]}: {token}"
        for token, line in zip(cited, batch.stdout.splitlines(), strict=True)
        if line.endswith(" commit") and line.split()[0] not in reachable
    ]
    assert stale == []


# --------- Code named in the docs exists (docs follow code) ---------

_PY_PATH = r"(?<![\w/.-])((?:tests/)?[a-z_][a-z0-9_/]*\.py)"
# `module.py:symbol[,symbol]` (a dotted symbol checks each part) and module.py (`symbol`).
# Numeric line references are not checked.
_CODE_REF_COLON = re.compile(_PY_PATH + r":([A-Za-z_][\w.]*(?:,[A-Za-z_][\w.]*)*)")
_CODE_REF_PAREN = re.compile(_PY_PATH + r" \(`([A-Za-z_][\w.]*)`")


def test_decision_code_references_resolve() -> None:
    """Every symbol DECISIONS.md cites by module still appears in that module.

    Paths resolve against the repository root, then ``src/alphaswarm``. A row
    whose code was renamed or deleted fails here until it is repointed.
    """
    src = ROOT / "src" / "alphaswarm"
    stale: list[str] = []
    for lineno, line in enumerate(DECISIONS.read_text(encoding="utf-8").splitlines(), 1):
        for pattern in (_CODE_REF_COLON, _CODE_REF_PAREN):
            for path, symbols in pattern.findall(line):
                target = next((base / path for base in (ROOT, src) if (base / path).is_file()), None)
                if target is None:
                    stale.append(f"line {lineno}: {path} (no such file)")
                    continue
                body = target.read_text(encoding="utf-8")
                stale.extend(
                    f"line {lineno}: {path}:{symbol}"
                    for symbol in symbols.split(",")
                    if not all(re.search(rf"\b{re.escape(part)}\b", body) for part in symbol.split("."))
                )
    assert stale == []


# A backticked name that looks like code: snake_case or an inner capital (`parse_agent_decision`, `StateStore`).
_BACKTICKED_NAME = re.compile(r"`([A-Za-z_]\w*)(?:\(\))?`")


def test_architecture_names_only_code_that_exists() -> None:
    """Every code-like name ARCHITECTURE.md puts in backticks still exists in the code.

    The haystack is the tracked source of src/, frontend/src/, scripts/ and eval/
    plus their file paths, so module and script names count too.
    """
    files = _tracked("src", "frontend/src", "scripts", "eval")
    corpus = "\n".join([*files, *(_read(rel) for rel in files if rel.endswith((".py", ".ts", ".tsx", ".j2")))])
    names = {
        name
        for name in _BACKTICKED_NAME.findall(_read("docs/ARCHITECTURE.md"))
        if "_" in name or any(char.isupper() for char in name[1:])
    }
    assert sorted(name for name in names if not re.search(rf"\b{re.escape(name)}\b", corpus)) == []


# --------- iCloud duplicates (T12.8) ---------

DUPLICATE_GLOB = "* [2-9].py"


def _gitignore_lines() -> list[str]:
    return [line.strip() for line in _read(".gitignore").splitlines()]


def _pyproject() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_gitignore_hides_icloud_duplicates() -> None:
    lines = _gitignore_lines()
    assert "* [2-9].*" in lines
    assert "* [2-9]" in lines


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        ("src/alphaswarm/config 2.py", True),
        (".env 3.example", True),
        ("AlphaSwarm-2/src 2", True),
        ("src/alphaswarm/config.py", False),
        ("tests/test_phase2.py", False),
    ],
)
def test_git_ignores_only_icloud_copies(path: str, ignored: bool) -> None:
    result = _git("check-ignore", "-q", "--no-index", path)
    assert (result.returncode == 0) is ignored


def test_pytest_skips_icloud_duplicate_test_files() -> None:
    addopts = shlex.split(_pyproject()["tool"]["pytest"]["ini_options"]["addopts"])
    assert f"--ignore-glob={DUPLICATE_GLOB}" in addopts


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        ("/Users/me/Documents/VS Code/AlphaSwarm/tests/test_config 2.py", True),
        ("/Users/me/dev/AlphaSwarm/src/alphaswarm/worker 3.py", True),
        ("/Users/me/Documents/VS Code/AlphaSwarm/tests/test_config.py", False),
        ("/Users/me/VS 2/AlphaSwarm/tests/test_web.py", False),
        ("/Users/me/dev/AlphaSwarm/tests/test_phase2.py", False),
    ],
)
def test_duplicate_glob_matches_only_icloud_copies(path: str, ignored: bool) -> None:
    assert fnmatch.fnmatch(path, DUPLICATE_GLOB) is ignored


# --------- Porter leftovers (T12.10 steps 5-6) ---------


def test_porter_leftovers_are_archived() -> None:
    assert _tracked("PROJECT_SPEC.md") == []
    assert (ROOT / "docs" / "history" / "original-spec.md").is_file()
    assert _tracked("docs/superpowers") == []
    design = _read("docs/design/inference-providers.md")
    assert ".secrets/inference.toml" not in design
    assert ".secrets/inference.json" in design


def test_current_docs_do_not_point_at_moved_files() -> None:
    current = (
        "README.md",
        "CLAUDE.md",
        "docs/ARCHITECTURE.md",
        "docs/DECISIONS.md",
        "docs/RUNBOOK.md",
        "docs/HISTORY.md",
    )
    assert [rel for rel in current if "docs/superpowers/" in _read(rel)] == []
    assert [rel for rel in current[:-1] if "PROJECT_SPEC.md" in _read(rel)] == []


# --------- Root clutter and ignores (T7.7, T12.11) ---------


def test_gitignore_covers_backups_and_coverage_output() -> None:
    lines = _gitignore_lines()
    for required in ("/data/", ".coverage", "htmlcov/"):
        assert required in lines
    assert "*.vue.js" not in lines
    assert "data/sec_tickers.json" not in lines


def test_neo4j_backup_dumps_are_ignored() -> None:
    result = _git("check-ignore", "-q", "--no-index", "data/backups/neo4j-20261003.dump")
    assert result.returncode == 0


def test_textual_is_not_a_dependency() -> None:
    names = {re.split(r"[<>=!~;\[ ]", dep, maxsplit=1)[0].lower() for dep in _pyproject()["project"]["dependencies"]}
    assert "textual" not in names


def test_design_prototype_left_the_frontend_tree() -> None:
    assert _tracked("frontend/design-reference") == []
    assert (ROOT / "docs" / "design" / "prototype" / "README.md").is_file()  # G-07 branch A only


# --------- Attribution (T12.6) ---------


def test_mailmap_maps_the_relay_identity_to_the_owner() -> None:
    result = _git("check-mailmap", "Gonmyh-7konwe-funmuw <newborn.jujitsu0w@icloud.com>")
    assert result.returncode == 0, result.stderr
    owner = "Avo Sarkissian <87339673+Avo-Sarkissian@users.noreply.github.com>"
    assert result.stdout.strip() == owner
