"""write_run_manifest: one SET on the Cycle, loud on a missing cycle (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph import schema_writes
from tests.support.manifests import make_manifest


async def test_writes_json_seed_and_tag() -> None:
    captured: list[tuple[Any, ...]] = []

    async def fake_write(fn: Any, *args: Any, op: str) -> int:
        captured.append((op, *args))
        return 1

    manifest = make_manifest(tag="p7-3-control")
    await schema_writes.write_run_manifest(fake_write, manifest.cycle_id, manifest)

    op, cycle_id, payload, sim_seed, tag = captured[0]
    assert op == "write_run_manifest"
    assert (cycle_id, sim_seed, tag) == (manifest.cycle_id, 4242, "p7-3-control")
    assert json.loads(payload)["schema"] == "alphaswarm.run-manifest/1"


async def test_missing_cycle_fails_loud() -> None:
    async def fake_write(fn: Any, *args: Any, op: str) -> int:
        return 0

    with pytest.raises(Neo4jWriteError) as exc_info:
        await schema_writes.write_run_manifest(fake_write, "missing", make_manifest())

    assert exc_info.value.op == "write_run_manifest"


def test_schema_has_the_experiment_tag_index() -> None:
    assert (
        "CREATE INDEX cycle_experiment_tag IF NOT EXISTS FOR (c:Cycle) ON (c.experiment_tag)"
        in schema_writes.SCHEMA_STATEMENTS
    )
