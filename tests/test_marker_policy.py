"""apply_marker_policy: sockets and live skips follow markers, never paths."""

from __future__ import annotations

import pytest

from tests.support.markers import apply_marker_policy

pytest_plugins = ["pytester"]

_INI = """
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
markers =
    neo4j: test db
    live_network: internet
    ollama: local ollama
"""

_SOURCE = """
import pytest

@pytest.mark.neo4j
async def test_db_async():
    pass

@pytest.mark.neo4j
@pytest.mark.asyncio()
async def test_db_explicit_function_loop():
    pass

@pytest.mark.neo4j
def test_db_sync():
    pass

@pytest.mark.live_network
def test_live():
    pass

@pytest.mark.ollama
async def test_model():
    pass

def test_plain():
    pass
"""


def _collect(pytester: pytest.Pytester, *, run_live: bool) -> dict[str, pytest.Item]:
    pytester.makeini(_INI)
    items = pytester.getitems(_SOURCE)
    apply_marker_policy(items, run_live=run_live)
    return {item.name: item for item in items}


def test_socket_markers_enable_sockets_and_plain_tests_stay_offline(
    pytester: pytest.Pytester,
) -> None:
    items = _collect(pytester, run_live=True)
    for name in ("test_db_async", "test_db_sync", "test_live", "test_model"):
        assert items[name].get_closest_marker("enable_socket") is not None, name
    assert items["test_plain"].get_closest_marker("enable_socket") is None


def test_neo4j_async_tests_run_on_the_session_loop(pytester: pytest.Pytester) -> None:
    items = _collect(pytester, run_live=False)
    for name in ("test_db_async", "test_db_explicit_function_loop"):
        marker = items[name].get_closest_marker("asyncio")
        assert marker is not None, name
        assert marker.kwargs == {"loop_scope": "session"}, name
    assert items["test_db_sync"].get_closest_marker("asyncio") is None


def test_live_tests_skip_without_run_live(pytester: pytest.Pytester) -> None:
    items = _collect(pytester, run_live=False)
    assert items["test_live"].get_closest_marker("skip") is not None
    assert items["test_model"].get_closest_marker("skip") is not None
    assert items["test_db_async"].get_closest_marker("skip") is None
    assert items["test_plain"].get_closest_marker("skip") is None


def test_live_tests_run_with_run_live(pytester: pytest.Pytester) -> None:
    items = _collect(pytester, run_live=True)
    assert items["test_live"].get_closest_marker("skip") is None
    assert items["test_model"].get_closest_marker("skip") is None
