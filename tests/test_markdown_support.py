"""The Markdown helpers reproduce GitHub's anchors and ignore code."""

from __future__ import annotations

import pytest

from tests.support.markdown import anchors, github_slug, h2_sections, links, preamble


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("Why it's interesting", "why-its-interesting"),
        ("Testing & CI", "testing--ci"),
        ("7. Memory budget", "7-memory-budget"),
        ("A0 — baseline (telemetry only)", "a0--baseline-telemetry-only"),
        ("`alphaswarm doctor`", "alphaswarm-doctor"),
        ('<a id="adr-governor"></a>Memory-aware ResourceGovernor', "memory-aware-resourcegovernor"),
        ("Headline numbers (v6.0)", "headline-numbers-v60"),
    ],
)
def test_github_slug_matches_github(heading: str, slug: str) -> None:
    assert github_slug(heading) == slug


def test_anchors_include_headings_html_ids_and_repeats() -> None:
    text = '# Title\n\n## Usage\n\n## Usage\n\n<a id="custom"></a>\n\n```\n## Not a heading\n```\n'
    assert anchors(text) == {"title", "usage", "usage-1", "custom"}


def test_links_skip_fenced_and_inline_code() -> None:
    text = (
        "See [the runbook](docs/RUNBOOK.md#memory-budget) and ![shot](docs/media/a.png).\n"
        "Inline `[not](a/link.md)` is code.\n"
        "```bash\n[also](not/a/link.md)\n```\n"
        '[![badge](https://img.example/b.svg)](LICENSE "title")\n'
    )
    assert links(text) == [
        (1, "docs/RUNBOOK.md#memory-budget"),
        (1, "docs/media/a.png"),
        (6, "https://img.example/b.svg"),
        (6, "LICENSE"),
    ]


def test_sections_and_preamble() -> None:
    text = "# T\n\nIntro\n\n## One\n\nBody 1\n```\n## fenced\n```\n\n## Two\n\nBody 2\n"
    assert preamble(text) == "# T\n\nIntro\n"
    sections = h2_sections(text)
    assert [title for title, _ in sections] == ["One", "Two"]
    assert "## fenced" in sections[0][1]
    assert sections[1][1].strip() == "Body 2"
