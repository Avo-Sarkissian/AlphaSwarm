"""Neo4j memory is bounded: the JVM otherwise sizes itself from the Docker VM."""

from __future__ import annotations

from alphaswarm.settings import PROJECT_ROOT

COMPOSE = PROJECT_ROOT / "docker-compose.yml"


def _service_lines(name: str) -> list[str]:
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {name}:")
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("   ") and line.strip():
            break  # next service
        if line and not line.startswith(" "):
            break  # next top-level key
        body.append(line.strip())
    return body


def test_neo4j_service_has_memory_caps() -> None:
    body = _service_lines("neo4j")
    for expected in (
        'NEO4J_server_memory_heap_initial__size: "1g"',
        'NEO4J_server_memory_heap_max__size: "1g"',
        'NEO4J_server_memory_pagecache_size: "512m"',
        'NEO4J_db_memory_transaction_total_max: "512m"',
        'JDK_JAVA_OPTIONS: "-XX:+ExitOnOutOfMemoryError"',
        "mem_limit: 2500m",
        "stop_grace_period: 60s",
    ):
        assert expected in body, expected


def test_the_test_database_keeps_its_own_small_caps() -> None:
    body = _service_lines("neo4j-test")
    assert 'NEO4J_server_memory_heap_max__size: "512m"' in body
    assert "mem_limit: 2500m" not in body
