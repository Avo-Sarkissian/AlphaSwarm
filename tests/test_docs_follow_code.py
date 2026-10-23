"""Docs that describe the service layer, the one-call report and structured output.

CLAUDE.md is owner-edited, so only its launcher line is checked here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _section(text: str, anchor: str) -> str:
    return text.split(f'<a id="{anchor}"></a>', 1)[1].split("### ", 1)[0]


def test_no_doc_launches_the_removed_module_level_app() -> None:
    for name in ("README.md", "docs/RUNBOOK.md", "docs/ARCHITECTURE.md", "CLAUDE.md"):
        assert "alphaswarm.web.app:app" not in _read(name), name


def test_readme_no_longer_advertises_a_react_report_agent() -> None:
    text = _read("README.md")
    assert "ReACT" not in text and "ReAct agent" not in text


def test_decisions_record_the_superseded_react_loop_and_chat_structured() -> None:
    text = _read("docs/DECISIONS.md")
    react = _section(text, "adr-report-react")
    assert "Superseded" in react and "one" in react.lower()
    assert "chat_structured" in _section(text, "adr-structured-output")
    lifespan = _section(text, "adr-web-lifespan")
    assert "alphaswarm web" in lifespan and "workers=1" in lifespan
    for anchor in ("p15-d-01", "p15-d-02", "p15-d-03"):
        row = text.split(f'<a id="{anchor}"></a>', 1)[1].split("\n", 1)[0]
        assert "| superseded |" in row, anchor


def test_decisions_describe_the_job_runner_not_route_tasks() -> None:
    text = _read("docs/DECISIONS.md")
    assert "until its route moves" not in _section(text, "adr-background-tasks")
    row = text.split('<a id="p41-d-08"></a>', 1)[1].split("\n", 1)[0]
    assert "JobRunner" in row and "bidirectional 409" not in row
