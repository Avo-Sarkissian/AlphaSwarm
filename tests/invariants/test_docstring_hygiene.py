"""Module docstrings state purpose, invariants and failure contract.

Review rounds, plan and task numbers and pitfall numbers belong in git history
and docs/DECISIONS.md, not in a module docstring.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import alphaswarm

SRC = Path(alphaswarm.__file__).resolve().parent

TRIMMED = (
    "cli.py",
    "ingestion/rss_provider.py",
    "ingestion/yfinance_provider.py",
    "web/replay_manager.py",
    "web/routes/holdings.py",
    "web/routes/report.py",
)
MAX_DOCSTRING_LINES = 25
PROCESS_TAG = re.compile(
    r"\b(?:[Cc]odex|[Gg]emini|REVIEWS?|Revision round|Pitfall\s*\d+|Plan \d+(?:\.\d+)?-\d+|"
    r"Task \d+|Phase \d+(?:\.\d+)?|[Qq]uick task|INGEST-\d+|HOLD-\d+)\b"
    r"|\b(?:D-\d{2}|T-\d{2}-\d{2}|KR-\d+\.\d+-\d+)\b"
)


def module_docstring(rel: str) -> str:
    return ast.get_docstring(ast.parse((SRC / rel).read_text(encoding="utf-8"))) or ""


@pytest.mark.parametrize("rel", TRIMMED)
def test_module_docstring_is_short(rel: str) -> None:
    doc = module_docstring(rel)
    assert doc, f"{rel} has no module docstring"
    assert len(doc.splitlines()) <= MAX_DOCSTRING_LINES, f"{rel}: {len(doc.splitlines())} lines"


@pytest.mark.parametrize("rel", TRIMMED)
def test_module_docstring_has_no_process_tags(rel: str) -> None:
    match = PROCESS_TAG.search(module_docstring(rel))
    assert match is None, f"{rel}: process tag {match.group(0)!r} in the module docstring"
