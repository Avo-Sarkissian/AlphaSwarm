"""pytest settings that CI relies on."""

from __future__ import annotations

import pytest


def _effective(pytestconfig: pytest.Config, key: str) -> object:
    """The value pytest acts on: an unset ``strict_*`` key falls back to the ``strict`` umbrella."""
    value = pytestconfig.getini(key)
    return pytestconfig.getini("strict") if value is None else value


def _is_targeted_ignore(entry: str) -> bool:
    """True for ``ignore:<message>:<WarningClass>:<module>`` with every part filled in."""
    action, message, category, module, *_ = [*entry.split(":"), "", "", "", ""]
    return action == "ignore" and all(part.strip() for part in (message, category, module))


def test_per_test_timeout_is_60_seconds(pytestconfig: pytest.Config) -> None:
    assert float(pytestconfig.getini("timeout")) == 60.0


@pytest.mark.parametrize("key", ["strict_markers", "strict_config", "strict_xfail"])
def test_markers_config_and_xfails_are_strict(pytestconfig: pytest.Config, key: str) -> None:
    # pytest 9 ignores --strict-* flags that arrive through addopts, so only the ini keys
    # (or the ``strict`` umbrella) keep the suite strict. ``strict_xfail`` is the canonical
    # name of ``xfail_strict``: a pinned bug that starts passing must fail the run.
    assert _effective(pytestconfig, key) is True


def test_warnings_are_errors_with_only_targeted_ignores(pytestconfig: pytest.Config) -> None:
    filters = pytestconfig.getini("filterwarnings")
    # "error" comes first; a later matching entry wins, so it can only carve out an exception,
    # and each exception names a message, a warning class and a module (docs/RUNBOOK.md section 7).
    assert filters[:1] == ["error"]
    assert [entry for entry in filters[1:] if not _is_targeted_ignore(entry)] == []


@pytest.mark.parametrize(
    ("entry", "targeted"),
    [
        ("ignore:datetime.datetime.utcnow:DeprecationWarning:yfinance", True),
        ("ignore", False),
        ("ignore::DeprecationWarning", False),
        ("ignore:datetime.datetime.utcnow:DeprecationWarning", False),
        ("default:datetime.datetime.utcnow:DeprecationWarning:yfinance", False),
    ],
)
def test_only_message_class_and_module_ignores_count_as_targeted(entry: str, targeted: bool) -> None:
    assert _is_targeted_ignore(entry) is targeted
