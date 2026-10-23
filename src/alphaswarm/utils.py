"""Shared utility functions for AlphaSwarm.

Functions here are used by both simulation and CLI layers.
Avoids reverse dependencies (e.g., simulation importing from CLI).
"""

from __future__ import annotations

import re


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
# (docs/DECISIONS.md#adr-security-2026-08): control and bidi/format characters become
# spaces, whitespace collapses (a newline cannot start a forged peer line), "<" and ">"
# are dropped (no fence tag can be formed), "[" and "]" become "(" and ")" (no
# "[agent_id|bracket]" token can be forged), and '"' becomes "'" (the quoted field
# stays unambiguous).
_PEER_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_PEER_TRANSLATION = str.maketrans({"<": None, ">": None, "[": "(", "]": ")", '"': "'"})


def sanitize_peer_rationale(text: str, max_len: int = 300) -> str:
    """Make another agent's rationale safe to quote inside a peer block.

    Returns at most *max_len* characters, plus a trailing "…" when it had to cut;
    the cut falls on the last space when there is one.
    """
    cleaned = _PEER_CONTROL_RE.sub(" ", text).translate(_PEER_TRANSLATION)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len]
    head = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return head.rstrip() + "…"
