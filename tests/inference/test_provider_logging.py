"""The inference modules log through structlog (docs/DECISIONS.md#adr-security-2026-08)."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import structlog
from structlog.testing import capture_logs

import alphaswarm.inference.budget as budget_module
import alphaswarm.inference.openai_provider as openai_module
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.types import ProviderRole

SRC = Path(__file__).resolve().parents[2] / "src" / "alphaswarm" / "inference"


@pytest.mark.parametrize(
    ("module", "component"),
    [
        ("openai_provider", "inference.openai"),
        ("anthropic_provider", "inference.anthropic"),
        ("rate_limit", "inference.rate_limit"),
        ("budget", "inference.budget"),
    ],
)
def test_module_logs_through_structlog(module: str, component: str) -> None:
    text = (SRC / f"{module}.py").read_text(encoding="utf-8")
    assert "logging.getLogger" not in text
    assert re.search(r"^import logging$", text, re.MULTILINE) is None
    assert f'structlog.get_logger(component="{component}")' in text


async def test_strict_downgrade_logs_a_warning_with_a_body_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_module, "log", structlog.get_logger(component="inference.openai"))
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] == 1:
            message = "response_format json_schema not supported " + "x" * 500
            return httpx.Response(400, json={"error": {"message": message}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider(
            ProviderRole.WORKER,
            "gpt-test",
            base_url="https://api.example.com/v1",
            api_key="test-key",
            client=client,
        )
        with capture_logs() as logs:
            await provider.chat(
                [{"role": "user", "content": "hi"}],
                response_schema={"type": "object", "properties": {}},
            )
    events = [e for e in logs if e["event"] == "openai_strict_schema_downgraded"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["model"] == "gpt-test"
    assert events[0]["status"] == 400
    assert "json_schema not supported" in events[0]["body_excerpt"]
    assert len(events[0]["body_excerpt"]) <= 200


def test_unpriced_model_warns_once_with_structured_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "log", structlog.get_logger(component="inference.budget"))
    meter = BudgetMeter(Decimal("1"), {})
    with capture_logs() as logs:
        meter._cost_of("mystery-model", 10, 10)
        meter._cost_of("mystery-model", 10, 10)
    events = [e for e in logs if e["event"] == "budget_model_unpriced"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert (events[0]["model"], events[0]["policy"]) == ("mystery-model", "ceiling")
