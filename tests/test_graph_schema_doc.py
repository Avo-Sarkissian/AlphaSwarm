"""docs/graph-schema.md names exactly what the code writes to Neo4j."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
DOC: Final = ROOT / "docs" / "graph-schema.md"
SRC: Final = ROOT / "src" / "alphaswarm"

NODE_WRITE: Final = re.compile(r"\b(?:CREATE|MERGE)\s*\(\s*\w*\s*:\s*([A-Z]\w*)")
REL_WRITE: Final = re.compile(r"\b(?:CREATE|MERGE)\s*\(\s*\w*\s*\)\s*-\s*\[\s*\w*\s*:\s*([A-Z_]+)")
SCHEMA_NAME: Final = re.compile(r"CREATE\s+(?:CONSTRAINT|INDEX)\s+(\w+)\s+IF NOT EXISTS")
ER_ENTITY: Final = re.compile(r"^ {4}([A-Z]\w*)\s*\{\s*$", re.M)
ER_REL: Final = re.compile(r"^ {4}([A-Z]\w*)\s+\S+\s+([A-Z]\w*)\s*:\s*([A-Z_]+)\s*$", re.M)


def _code() -> str:
    files = sorted(p for p in SRC.rglob("*.py") if p.stem.isidentifier())
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def _mermaid() -> str:
    match = re.search(r"```mermaid\n(.*?)\n```", DOC.read_text(encoding="utf-8"), re.S)
    assert match, "docs/graph-schema.md has no mermaid block"
    return match.group(1)


def test_doc_lists_exactly_the_written_labels() -> None:
    assert set(ER_ENTITY.findall(_mermaid())) == set(NODE_WRITE.findall(_code()))


def test_doc_lists_exactly_the_written_relationships() -> None:
    documented = {rel for _, _, rel in ER_REL.findall(_mermaid())}
    assert documented == set(REL_WRITE.findall(_code()))


def test_doc_lists_every_schema_statement() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = sorted(name for name in set(SCHEMA_NAME.findall(_code())) if f"`{name}`" not in text)
    assert missing == []
