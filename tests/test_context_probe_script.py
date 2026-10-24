"""scripts/context_probe.py summarises a market block without Neo4j or network."""

from __future__ import annotations

from types import ModuleType

from alphaswarm.types import EntityType, SeedEntity
from tests.support.scripts import load_script

BLOCK = (
    "== ZZZT Holdings (ZZZT) ==\nPrice: $12.34 (as of 2026-10-02 20:00 UTC)\nRecent headlines:\n"
    "  - Deal talk lifts shares\n  - Analysts revisit targets\n\n"
    "== Industrial Automation ==\nRecent headlines:\n  - Robots everywhere"
)


def _load() -> ModuleType:
    return load_script("context_probe")


def _entities() -> list[SeedEntity]:
    return [
        SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5, ticker="ZZZT"),
        SeedEntity(name="Private Robotics Startup", type=EntityType.COMPANY, relevance=0.8, sentiment=0.4),
        SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.6, sentiment=0.2),
    ]


def test_summarize_block_counts_prices_and_headlines() -> None:
    row = _load().summarize_block("seed-a", _entities(), BLOCK)
    assert (row.companies, row.resolved, row.non_empty) == (2, ("ZZZT",), True)
    assert (row.price_lines, row.headline_lines, row.chars) == (1, 3, len(BLOCK))


def test_missing_block_is_empty() -> None:
    row = _load().summarize_block("seed-b", _entities(), None)
    assert (row.non_empty, row.price_lines, row.headline_lines, row.chars) == (False, 0, 0, 0)


def test_markdown_table_has_one_row_per_seed_and_a_total() -> None:
    script = _load()
    table = script.markdown_table(
        [
            script.summarize_block("seed-a", _entities(), BLOCK),
            script.summarize_block("seed-b", _entities(), None),
        ]
    )
    lines = table.splitlines()
    assert lines[0].startswith("| seed |") and len(lines) == 5
    assert lines[2] == "| seed-a | 2 | ZZZT | yes | 1 | 3 | " + str(len(BLOCK)) + " |"
    assert lines[3] == "| seed-b | 2 | ZZZT | no | 0 | 0 | 0 |"
    assert lines[-1] == "| non-empty | 1/2 |  |  |  |  |  |"


async def test_no_write_graph_returns_the_probe_id_and_writes_nothing() -> None:
    script = _load()
    graph = script._NoWriteGraph()
    assert await graph.create_cycle_with_seed_event("rumor", object(), num_rounds=2) == script.PROBE_CYCLE_ID
