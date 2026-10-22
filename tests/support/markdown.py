"""Markdown helpers for the documentation tests: GitHub anchors, links, sections."""

from __future__ import annotations

import re
from typing import Final

_FENCE: Final = re.compile(r"^\s*(```|~~~)")
_HEADING: Final = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HTML_ANCHOR: Final = re.compile(r'<a\s+(?:id|name)="([^"]+)"\s*>')
_LINK_TARGET: Final = re.compile(r'\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
_INLINE_CODE: Final = re.compile(r"`[^`\n]*`")


def _outside_fences(markdown: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append((number, line))
    return lines


def github_slug(heading: str) -> str:
    """The anchor GitHub generates for a heading's text."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(markdown: str) -> set[str]:
    """Every anchor a link may target: heading slugs (-1, -2 for repeats) and <a id>."""
    found: set[str] = set()
    counts: dict[str, int] = {}
    for _, line in _outside_fences(markdown):
        found.update(_HTML_ANCHOR.findall(line))
        match = _HEADING.match(line)
        if match is None:
            continue
        slug = github_slug(match.group(2))
        seen = counts.get(slug, 0)
        found.add(slug if seen == 0 else f"{slug}-{seen}")
        counts[slug] = seen + 1
    return found


def links(markdown: str) -> list[tuple[int, str]]:
    """(line number, target) of every link and image outside code."""
    return [
        (number, match.group(1))
        for number, line in _outside_fences(markdown)
        for match in _LINK_TARGET.finditer(_INLINE_CODE.sub("", line))
    ]


def h2_sections(markdown: str) -> list[tuple[str, str]]:
    """[(title, body)] for each level-2 heading outside code, in document order."""
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            sections.append((line[3:].strip(), []))
            continue
        if sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(body)) for title, body in sections]


def preamble(markdown: str) -> str:
    """Everything before the first level-2 heading."""
    out: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)
