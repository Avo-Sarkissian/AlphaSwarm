"""Offline tests for the neo4j-test safety guards in tests/conftest.py (C-TEST-03).

They run without Docker: the guards are plain functions, and the database
check gets a fake driver.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from tests.conftest import (
    FORBIDDEN_NEO4J_PORT,
    NEO4J_TEST_AUTH,
    NEO4J_TEST_URI,
    _refuse_forbidden_port,
    _refuse_nonempty_database,
)


def test_the_test_target_is_loopback_7688_with_the_throwaway_credential() -> None:
    parts = urlsplit(NEO4J_TEST_URI)
    assert (parts.hostname, parts.port) == ("127.0.0.1", 7688)
    assert parts.port != FORBIDDEN_NEO4J_PORT
    assert NEO4J_TEST_AUTH == ("neo4j", "alphaswarm-test-only")


@pytest.mark.parametrize(
    "uri",
    ["bolt://127.0.0.1:7687", "bolt://localhost:7687", "neo4j://127.0.0.1", "bolt://127.0.0.1"],
)
def test_the_dev_port_is_refused_with_exit_code_3(uri: str) -> None:
    with pytest.raises(pytest.exit.Exception) as info:
        _refuse_forbidden_port(uri)
    assert info.value.returncode == 3
    assert "7687" in info.value.msg


def test_the_test_port_is_allowed() -> None:
    _refuse_forbidden_port("bolt://127.0.0.1:7688")


class _FakeResult:
    def __init__(self, cycles: int) -> None:
        self._cycles = cycles

    async def single(self) -> dict[str, int]:
        return {"n": self._cycles}


class _FakeSession:
    def __init__(self, cycles: int) -> None:
        self._cycles = cycles

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def run(self, query: str, **params: object) -> _FakeResult:
        assert query == "MATCH (c:Cycle) RETURN count(c) AS n"
        return _FakeResult(self._cycles)


class _FakeDriver:
    def __init__(self, cycles: int) -> None:
        self._cycles = cycles

    def session(self, database: str) -> _FakeSession:
        assert database == "neo4j"
        return _FakeSession(self._cycles)


async def test_a_database_that_already_holds_cycles_is_refused() -> None:
    with pytest.raises(pytest.exit.Exception) as info:
        await _refuse_nonempty_database(_FakeDriver(cycles=2))  # type: ignore[arg-type]
    assert info.value.returncode == 3
    assert "2 Cycle node(s)" in info.value.msg
    assert "scripts/neo4j_test.sh reset" in info.value.msg


async def test_an_empty_database_passes() -> None:
    await _refuse_nonempty_database(_FakeDriver(cycles=0))  # type: ignore[arg-type]
