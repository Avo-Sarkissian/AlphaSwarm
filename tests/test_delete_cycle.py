"""delete_cycle: bounded batches, safe order, loud outages."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j.exceptions import ServiceUnavailable

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.graph import GraphStateManager, schema_writes

CYCLE = "00000000-0000-4000-8000-0000000000a1"


class Runners:
    def __init__(self, nodes: int) -> None:
        self.nodes = nodes
        self.reads: list[str] = []
        self.statements: list[tuple[str, str, dict[str, Any]]] = []

    async def read(self, fn: Any, *args: Any, op: str) -> int:
        self.reads.append(op)
        return self.nodes

    async def auto_commit(self, query: str, /, *, op: str, **params: Any) -> None:
        self.statements.append((query, op, params))


async def test_deletes_in_batches_and_the_cycle_node_last() -> None:
    runners = Runners(nodes=412)

    removed = await schema_writes.delete_cycle(runners.read, runners.auto_commit, CYCLE, batch_size=250)

    assert removed == 412
    assert runners.reads == ["delete_cycle"]
    queries = [query for query, _, _ in runners.statements]
    assert len(queries) == 6
    assert all(op == "delete_cycle" for _, op, _ in runners.statements)
    assert all(params == {"cycle_id": CYCLE} for _, _, params in runners.statements)
    for query, label in zip(queries[:4], (":INFLUENCED_BY", ":RationaleEpisode", ":Post", ":Decision"), strict=True):
        assert label in query and "IN TRANSACTIONS OF 250 ROWS" in query
    assert ":ShockEvent" in queries[4]
    assert queries[5].lstrip().startswith("MATCH (c:Cycle") and "DETACH DELETE c" in queries[5]


async def test_unknown_cycle_runs_no_statement() -> None:
    runners = Runners(nodes=0)
    assert await schema_writes.delete_cycle(runners.read, runners.auto_commit, CYCLE) == 0
    assert runners.statements == []


@pytest.mark.parametrize("batch_size", [0, -1, 100_001])
async def test_batch_size_is_bounded(batch_size: int) -> None:
    runners = Runners(nodes=10)
    with pytest.raises(ValueError, match="batch_size"):
        await schema_writes.delete_cycle(runners.read, runners.auto_commit, CYCLE, batch_size=batch_size)
    assert runners.reads == []


class _DownSession:
    async def __aenter__(self) -> _DownSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def run(self, *args: object, **kwargs: object) -> object:
        raise ServiceUnavailable("simulated outage")


class _DownDriver:
    def session(self, **kwargs: object) -> _DownSession:
        return _DownSession()


async def test_auto_commit_maps_a_driver_outage() -> None:
    gm = GraphStateManager(_DownDriver(), [])  # type: ignore[arg-type]
    with pytest.raises(Neo4jUnavailableError) as exc_info:
        await gm._auto_commit("RETURN 1", op="delete_cycle")
    assert exc_info.value.op == "delete_cycle"
