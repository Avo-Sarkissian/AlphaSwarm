"""Tests for structured logging configuration."""

from __future__ import annotations

import json

import pytest
import structlog

from alphaswarm.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_structlog() -> None:  # noqa: PT004
    """Reset structlog state after each test to prevent cross-test pollution."""
    yield  # type: ignore[misc]
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output mode produces parseable JSON with required fields."""
    configure_logging(log_level="INFO", json_output=True)
    logger = get_logger(component="test")
    logger.info("test event", key="value")

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["event"] == "test event"
    assert parsed["key"] == "value"
    assert parsed["level"] == "info"
    assert "timestamp" in parsed


def test_console_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Console output mode produces human-readable (non-JSON) output."""
    configure_logging(log_level="INFO", json_output=False)
    logger = get_logger()
    logger.info("test console event")

    captured = capsys.readouterr()
    # Console output should NOT be valid JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out.strip())
    assert "test console event" in captured.out


def test_correlation_binding(capsys: pytest.CaptureFixture[str]) -> None:
    """Contextvars bindings appear in JSON output for per-agent correlation."""
    configure_logging(log_level="INFO", json_output=True)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        agent_id="quant_03",
        bracket="quants",
        cycle_id="test-cycle-123",
    )
    logger = get_logger()
    logger.info("agent processing")

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["agent_id"] == "quant_03"
    assert parsed["bracket"] == "quants"
    assert parsed["cycle_id"] == "test-cycle-123"
    assert parsed["event"] == "agent processing"

    structlog.contextvars.clear_contextvars()


def test_log_level_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    """Log level filtering suppresses messages below the configured level."""
    configure_logging(log_level="WARNING", json_output=True)
    logger = get_logger()
    logger.info("should not appear")
    logger.warning("should appear")

    captured = capsys.readouterr()
    assert "should not appear" not in captured.out
    assert "should appear" in captured.out


def test_context_packet_fields_not_in_pii_redaction_set() -> None:
    """Phase 40 ISOL-04 canary: ContextPacket field names must NOT be in the PII
    redaction set. If a future maintainer adds 'market', 'news', or 'entities'
    to _LITERAL_NORMALIZED, ContextPacket log events would be silently corrupted
    and integration tests that assert 'market' key presence would start failing.
    """
    from alphaswarm.logging import _LITERAL_NORMALIZED

    assert "market" not in _LITERAL_NORMALIZED
    assert "news" not in _LITERAL_NORMALIZED
    assert "entities" not in _LITERAL_NORMALIZED


# ---------------------------------------------------------------------------
# T11.1: tracebacks reach the logs, local variables never do
# ---------------------------------------------------------------------------


def _raise_with_canary_local() -> None:
    # Built at runtime so the joined value never appears in this file's source,
    # which a traceback would otherwise print as code context.
    secret = "".join(["sk-", "LOCAL", "-CANARY"])
    raise ValueError(f"boom ({len(secret)} chars)")


def _walk_keys(node: object) -> set[str]:
    if isinstance(node, dict):
        keys = set(node)
        for value in node.values():
            keys |= _walk_keys(value)
        return keys
    if isinstance(node, list):
        found: set[str] = set()
        for value in node:
            found |= _walk_keys(value)
        return found
    return set()


def test_json_exception_has_structured_traceback_without_locals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(log_level="INFO", json_output=True)
    logger = get_logger(component="test")
    try:
        _raise_with_canary_local()
    except ValueError:
        logger.exception("task_failed")

    line = capsys.readouterr().out.strip()
    parsed = json.loads(line)
    assert "exc_info" not in parsed
    stack = parsed["exception"]
    assert stack[0]["exc_type"] == "ValueError"
    assert stack[0]["exc_value"] == "boom (15 chars)"
    assert [f["name"] for f in stack[0]["frames"]][-1] == "_raise_with_canary_local"
    assert "locals" not in _walk_keys(stack)
    assert "LOCAL-CANARY" not in line


def test_json_exception_from_an_explicit_exc_info_keeps_the_cause_chain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(log_level="INFO", json_output=True)
    logger = get_logger(component="test")
    try:
        try:
            _raise_with_canary_local()
        except ValueError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        logger.error("simulation_failed", exc_info=outer)

    parsed = json.loads(capsys.readouterr().out.strip())
    assert [entry["exc_type"] for entry in parsed["exception"]] == ["RuntimeError", "ValueError"]


def test_console_exception_never_prints_locals(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_level="INFO", json_output=False)
    logger = get_logger(component="test")
    try:
        _raise_with_canary_local()
    except ValueError:
        logger.exception("task_failed")

    out = capsys.readouterr().out
    assert "ValueError" in out
    assert "LOCAL-CANARY" not in out
