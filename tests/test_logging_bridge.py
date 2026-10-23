"""stdlib records go through the same redacting structlog chain (docs/DECISIONS.md#adr-security-2026-08)."""

from __future__ import annotations

import contextlib
import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from alphaswarm.logging import BRIDGE_HANDLER_NAME, configure_logging, reset_stdlib_bridge

FAKE_KEY = "sk-test-ABCDEFGHIJKLMNOP1234"


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    # Restore the exact prior config, not reset_defaults(): loggers cached earlier
    # in the session keep the old processors list, and capture_logs() in later
    # tests patches that list in place.
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)
    reset_stdlib_bridge()


def _lines(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def uvicorn_loggers() -> Iterator[None]:
    """Put the uvicorn loggers back as they were: uvicorn.Config applies uvicorn's
    LOGGING_CONFIG to the process-wide loggers."""
    saved = {}
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        saved[name] = (list(logger.handlers), logger.propagate, logger.level)
    yield
    for name, (handlers, propagate, level) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.propagate = propagate
        logger.setLevel(level)


async def _never_called_app(scope: object, receive: object, send: object) -> None:
    raise AssertionError("the logging tests never serve a request")


@pytest.mark.usefixtures("uvicorn_loggers")
def test_a_direct_uvicorn_launch_is_bridged_too(capsys: pytest.CaptureFixture[str]) -> None:
    """`uvicorn alphaswarm.web.app:app` applies uvicorn's default log_config, which gives
    its loggers their own handlers and stops propagation. Configuring logging (the web
    lifespan does) takes them over, so an ASGI traceback and the access lines are
    redacted like every other line."""
    import uvicorn

    uvicorn.Config(app=_never_called_app)
    assert logging.getLogger("uvicorn").handlers
    assert not logging.getLogger("uvicorn.access").propagate
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    try:
        raise RuntimeError(f"upstream rejected {FAKE_KEY}")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", f"/api/health?key={FAKE_KEY}", "1.1", 200
    )

    captured = capsys.readouterr()
    assert FAKE_KEY not in buffer.getvalue() + captured.out + captured.err
    error_line, access_line = _lines(buffer)
    assert error_line["event"] == "Exception in ASGI application"
    exception = error_line["exception"]
    assert isinstance(exception, list)
    assert exception[0]["exc_value"] == "upstream rejected [REDACTED_SECRET]"
    assert access_line["event"] == '127.0.0.1:50000 - "GET /api/health?key=[REDACTED_SECRET] HTTP/1.1" 200'


@pytest.mark.usefixtures("uvicorn_loggers")
def test_a_disabled_uvicorn_access_log_stays_off() -> None:
    """`uvicorn --no-access-log` leaves uvicorn.access without handlers and without
    propagation; the bridge keeps it that way instead of turning access lines on."""
    import uvicorn

    uvicorn.Config(app=_never_called_app, access_log=False)
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    logging.getLogger("uvicorn.access").info('127.0.0.1:50000 - "GET /api/health HTTP/1.1" 200')
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    [line] = _lines(buffer)
    assert line["event"] == "Application startup complete."


def test_stdlib_warning_with_a_fake_key_is_redacted() -> None:
    """A key in a third-party SDK warning never reaches the terminal."""
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    logging.getLogger("openai").warning("Retrying request with key %s after 429", FAKE_KEY)
    assert FAKE_KEY not in buffer.getvalue()
    [line] = _lines(buffer)
    assert line["level"] == "warning"
    assert line["event"] == "Retrying request with key [REDACTED_SECRET] after 429"
    assert "timestamp" in line


def test_stdlib_info_lines_are_kept_and_structured() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    [line] = _lines(buffer)
    assert line["event"] == "Application startup complete."
    assert line["level"] == "info"


def test_chatty_http_client_loggers_stay_at_warning() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    logging.getLogger("httpx").info('HTTP Request: POST http://localhost:11434/api/chat "200 OK"')
    assert buffer.getvalue() == ""


def test_stdlib_exception_is_rendered_without_locals() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    try:
        secret = "".join(["sk-", "LOCAL", "-CANARY-0000"])
        raise RuntimeError(f"failed ({len(secret)} chars)")
    except RuntimeError:
        logging.getLogger("anthropic").exception("request failed")
    [line] = _lines(buffer)
    exception = line["exception"]
    assert isinstance(exception, list)
    assert exception[0]["exc_type"] == "RuntimeError"
    assert "LOCAL-CANARY" not in buffer.getvalue()


def test_console_mode_bridges_too() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=False, stream=buffer)
    logging.getLogger("openai").warning("key %s", FAKE_KEY)
    assert "[REDACTED_SECRET]" in buffer.getvalue()
    assert FAKE_KEY not in buffer.getvalue()


def test_console_mode_scrubs_bridged_exception_text() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=False, stream=buffer)
    try:
        raise RuntimeError(f"upstream rejected {FAKE_KEY}")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    assert "RuntimeError: upstream rejected [REDACTED_SECRET]" in buffer.getvalue()
    assert FAKE_KEY not in buffer.getvalue()


def test_configuring_twice_installs_one_bridge_handler() -> None:
    configure_logging(log_level="INFO", json_output=True, stream=io.StringIO())
    configure_logging(log_level="INFO", json_output=True, stream=io.StringIO())
    names = [handler.get_name() for handler in logging.getLogger().handlers]
    assert names.count(BRIDGE_HANDLER_NAME) == 1


def test_structlog_events_honour_the_stream() -> None:
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_output=True, stream=buffer)
    structlog.get_logger(component="test").info("bridge_ready", items=2)
    [line] = _lines(buffer)
    assert (line["event"], line["items"]) == ("bridge_ready", 2)


def test_default_stream_follows_the_current_stdout() -> None:
    """Without stream=, nothing keeps the stdout that was current at configure time:
    pytest's capsys closes its stream after a test, and a kept reference would make
    every later log line raise "I/O operation on closed file"."""
    first, second = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(first):
        configure_logging(log_level="INFO", json_output=True)
    with contextlib.redirect_stdout(second):
        logging.getLogger("uvicorn.error").info("stdlib line")
        structlog.get_logger(component="test").info("structlog_line")
    assert first.getvalue() == ""
    assert "stdlib line" in second.getvalue()
    assert "structlog_line" in second.getvalue()
