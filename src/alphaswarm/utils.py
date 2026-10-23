"""Shared utility functions for AlphaSwarm.

Functions here are used by both simulation and CLI layers.
Avoids reverse dependencies (e.g., simulation importing from CLI).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final


def sanitize_rationale(text: str, max_len: int = 80) -> str:
    """Strip control characters, normalize whitespace, truncate.

    Moved from cli._sanitize_rationale to shared utility to avoid
    simulation -> CLI import dependency (Codex review concern).
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned


# Peer rationales are other agents' model output, which an RSS headline can steer in
# Round 1, so they are neutralised before another agent reads them
# (docs/DECISIONS.md#adr-security-2026-08): every Unicode control, format, line- and
# paragraph-separator character (categories Cc, Cf, Zl and Zp: zero-width, bidi and the
# invisible tag characters included) becomes a space, the rule config.sanitize_headline
# applies to headlines; whitespace collapses (a newline cannot start a forged peer
# line), "<" and ">" are dropped (no fence tag can be formed), "[" and "]" become "("
# and ")" (no "[agent_id|bracket]" token can be forged), and '"' becomes "'" (the
# quoted field stays unambiguous).
_PEER_SPACE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})
_PEER_TRANSLATION = str.maketrans({"<": None, ">": None, "[": "(", "]": ")", '"': "'"})


def sanitize_peer_rationale(text: str, max_len: int = 300) -> str:
    """Make another agent's rationale safe to quote inside a peer block.

    Returns at most *max_len* characters, plus a trailing "…" when it had to cut;
    the cut falls on the last space when there is one.
    """
    cleaned = "".join(" " if unicodedata.category(char) in _PEER_SPACE_CATEGORIES else char for char in text)
    cleaned = " ".join(cleaned.translate(_PEER_TRANSLATION).split())
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len]
    head = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return head.rstrip() + "…"
