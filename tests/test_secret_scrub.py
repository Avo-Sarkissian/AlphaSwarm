"""API-key shapes are scrubbed from every logged string (docs/DECISIONS.md#adr-holdings-isolation)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog

from alphaswarm.logging import configure_logging, pii_redaction_processor

SECRETS = [
    "sk-test-ABCDEFGHIJKLMNOP1234",
    "sk-ant-api03-ABCDEFGHIJKL",
    "sk-proj-ABCDEFGHIJKL1234",
    "nvapi-ABCDEFGHIJKLMNOP",
    "Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc",
]


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    # Restore the exact prior config, not reset_defaults(): loggers cached earlier
    # in the session keep the old processors list, and capture_logs() in later
    # tests patches that list in place.
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_shapes_are_scrubbed_from_any_string_value(secret: str) -> None:
    out = pii_redaction_processor(
        None,
        "warning",
        {
            "event": f"request failed with {secret} attached",
            "error": f"401 for {secret}",
            "nested": {"detail": [secret]},
        },
    )
    assert secret not in repr(out)
    assert out["event"] == "request failed with [REDACTED_SECRET] attached"
    assert out["nested"]["detail"] == ["[REDACTED_SECRET]"]


@pytest.mark.parametrize(
    "text",
    ["task-1234567890 finished", "risk-adjusted return", "Bearer token missing", "sk-short", "desk-ABCDEFGHIJ"],
)
def test_ordinary_text_is_untouched(text: str) -> None:
    assert pii_redaction_processor(None, "info", {"event": text})["event"] == text


def test_free_text_keys_get_both_scrubs() -> None:
    out = pii_redaction_processor(
        None,
        "info",
        {"message": "paid $1,234.56 with sk-test-ABCDEFGHIJKLMNOP1234"},
    )
    assert out["message"] == "paid [REDACTED_CURRENCY] with [REDACTED_SECRET]"


def test_scrub_runs_in_the_configured_chain(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_level="INFO", json_output=True)
    structlog.get_logger(component="test").error(
        "upstream_error",
        error="401 sk-test-ABCDEFGHIJKLMNOP1234",
    )
    out = capsys.readouterr().err
    assert "sk-test-ABCDEFGHIJKLMNOP1234" not in out
    assert "[REDACTED_SECRET]" in out


@pytest.mark.parametrize("json_output", [True, False], ids=["json", "console"])
def test_exception_text_is_scrubbed_in_both_modes(json_output: bool, capsys: pytest.CaptureFixture[str]) -> None:
    """The traceback is rendered before the redactor in console mode too
    (ALPHASWARM_DEBUG=true), so a key quoted in an exception message is scrubbed."""
    configure_logging(log_level="INFO", json_output=json_output)
    try:
        raise RuntimeError("401 for sk-test-ABCDEFGHIJKLMNOP1234")
    except RuntimeError:
        structlog.get_logger(component="test").exception("upstream_error")
    out = capsys.readouterr().err
    assert "sk-test-ABCDEFGHIJKLMNOP1234" not in out
    assert "RuntimeError" in out
    assert "401 for [REDACTED_SECRET]" in out
