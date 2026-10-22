"""pytest settings that CI relies on."""

from __future__ import annotations

import pytest


def test_per_test_timeout_is_60_seconds(pytestconfig: pytest.Config) -> None:
    assert float(pytestconfig.getini("timeout")) == 60.0
