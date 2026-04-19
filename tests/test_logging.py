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
