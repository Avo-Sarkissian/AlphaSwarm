"""Golden-file assertions for read models, report templates and wire fixtures.

``UPDATE_GOLDEN=1`` rewrites the golden instead of comparing. Regenerate only in a commit
whose purpose explains the diff, and never in CI.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import difflib
import json
import os
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Final

from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime
from pydantic import BaseModel

GOLDEN_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "golden"
UPDATE_ENV: Final = "UPDATE_GOLDEN"

_UUID_RE: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ISO_TS_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")

GoldenValue = str | Mapping[str, object] | Sequence[object]


def normalize(obj: object) -> object:
    """Make ``obj`` stable for a golden file.

    UUIDs become ``"<UUID:n>"`` numbered by first appearance, ISO datetimes and neo4j
    ``DateTime``/``Date`` become ``"<TS>"``, floats are rounded to 6 dp (``-0.0`` -> ``0.0``),
    enums become their values, dataclasses and pydantic models become dicts. Strings are
    scanned for embedded UUIDs and timestamps. Dict keys are sorted when dumped.
    """
    uuids: dict[str, str] = {}

    def _uuid(match: re.Match[str]) -> str:
        return uuids.setdefault(match.group(0), f"<UUID:{len(uuids) + 1}>")

    def _text(value: str) -> str:
        return _ISO_TS_RE.sub("<TS>", _UUID_RE.sub(_uuid, value))

    def _walk(value: object) -> object:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, Enum):
            return _walk(value.value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            rounded = round(value, 6)
            return 0.0 if rounded == 0 else rounded
        if isinstance(value, str):
            return _text(value)
        if isinstance(value, (dt.datetime, dt.date, Neo4jDateTime, Neo4jDate)):
            return "<TS>"
        if isinstance(value, BaseModel):
            return _walk(value.model_dump(mode="json"))
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return _walk(dataclasses.asdict(value))
        if isinstance(value, Mapping):
            return {_key(k): _walk(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_walk(v) for v in value]
        if isinstance(value, (set, frozenset)):
            return sorted((_walk(v) for v in value), key=repr)
        raise TypeError(f"normalize: unsupported type {type(value).__name__}")

    def _key(key: object) -> str:
        walked = _walk(key)
        return walked if isinstance(walked, str) else json.dumps(walked, sort_keys=True)

    return _walk(obj)


def _render(actual: GoldenValue, *, normalize_values: bool) -> str:
    if isinstance(actual, str):
        text = normalize(actual) if normalize_values else actual
        if not isinstance(text, str):
            raise TypeError("normalize() of a str must return a str")
        return text if text.endswith("\n") else text + "\n"
    data = normalize(actual) if normalize_values else actual
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assert_golden_file(path: Path, actual: GoldenValue, *, normalize_values: bool = True) -> None:
    """Compare ``actual`` with the golden at ``path`` (any repo path), or rewrite it."""
    rendered = _render(actual, normalize_values=normalize_values)
    if os.environ.get(UPDATE_ENV) == "1":
        if os.environ.get("CI") == "true":
            raise AssertionError(f"{UPDATE_ENV}=1 is not allowed in CI")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(
            f"golden file missing: {path}\nCreate it with {UPDATE_ENV}=1 and review it before committing."
        )
    expected = path.read_text(encoding="utf-8")
    if expected != rendered:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"{path} (golden)",
                tofile=f"{path} (actual)",
            )
        )
        raise AssertionError(
            f"golden mismatch: {path}\n{diff}\n"
            f"If the change is intended, rerun with {UPDATE_ENV}=1 and explain it in the "
            "commit body."
        )


def assert_golden(rel_path: str, actual: GoldenValue, *, normalize_values: bool = True) -> None:
    """Compare ``actual`` with ``tests/golden/<rel_path>``, or rewrite it."""
    relative = Path(rel_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"golden path must stay under {GOLDEN_ROOT}: {rel_path}")
    assert_golden_file(GOLDEN_ROOT / relative, actual, normalize_values=normalize_values)
