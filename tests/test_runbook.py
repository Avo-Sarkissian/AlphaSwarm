"""docs/RUNBOOK.md quotes the code it documents: memory caps, thresholds, config schema."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alphaswarm.inference.config import InferenceConfig
from alphaswarm.settings import GovernorSettings
from tests.support.markdown import h2_sections

ROOT: Final = Path(__file__).resolve().parents[1]
RUNBOOK: Final = ROOT / "docs" / "RUNBOOK.md"


def _section(title: str) -> str:
    sections = dict(h2_sections(RUNBOOK.read_text(encoding="utf-8")))
    assert title in sections, f"RUNBOOK has no '## {title}' section"
    return sections[title]


def test_memory_budget_quotes_the_compose_cap_and_the_governor_thresholds() -> None:
    body = _section("Memory budget")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    cap = re.search(r"(?m)^\s+mem_limit:\s*(\S+)\s*$", compose)
    assert cap, "docker-compose.yml has no mem_limit"
    governor = GovernorSettings()
    for needle in (
        f"mem_limit: {cap.group(1)}",
        f"{governor.memory_throttle_percent:g}%",
        f"{governor.memory_pause_percent:g}%",
        "OLLAMA_NUM_PARALLEL",
        "Docker Desktop 3-4 GiB",
    ):
        assert needle in body, needle


def test_memory_budget_has_no_unfilled_measurements() -> None:
    assert re.findall(r"<[a-z][^>]*>", _section("Memory budget")) == []


def test_cloud_config_example_validates() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    reference = re.search(r"(?ms)^### Cloud mode quick reference\n(.*?)(?=^#{2,3} |\Z)", text)
    assert reference, "RUNBOOK has no '### Cloud mode quick reference' subsection"
    block = re.search(r"```json\n(.*?)```", reference.group(1), re.S)
    assert block, "no JSON example in the cloud mode reference"
    config = InferenceConfig.model_validate_json(block.group(1))
    assert config.allow_cloud_advisory is False


def test_migration_notes_live_in_the_runbook() -> None:
    body = _section("Migrating an existing Neo4j install")
    assert "docker rm -f neo4j" in body
    assert "ALTER CURRENT USER SET PASSWORD" in body
