"""D-12 + Pitfall 4: auto-apply @pytest.mark.enable_socket to every test in this subtree.

Without this hook, every integration test would need to individually decorate
itself. The hook runs at collection time and adds the marker to any item whose
path contains "tests/integration".
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-apply enable_socket marker to all tests under tests/integration/."""
    for item in items:
        fspath = str(item.fspath)
        if "tests/integration" in fspath or "tests\\integration" in fspath:
            item.add_marker(pytest.mark.enable_socket)
