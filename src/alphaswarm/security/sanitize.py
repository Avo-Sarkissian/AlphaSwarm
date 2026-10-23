"""Sanitizers for untrusted or model-generated text before it reaches a prompt or the UI.

Entity names and headlines come from the orchestrator and remote feeds; peer and
display rationales come from worker output. None of it may forge prompt structure
(docs/DECISIONS.md#adr-security-2026-08).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# ---------------------------------------------------------------------------
# Entity name sanitization (Phase 13, D-11, D-12)
# ---------------------------------------------------------------------------


def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name for safe prompt interpolation (D-11, D-12).

    Truncates to 100 characters and strips Unicode Cc (control) and
    Cf (format) categories. Preserves standard punctuation including
    hyphens, periods, apostrophes, ampersands, and parentheses.
    """
    truncated = name[:100]
    return "".join(c for c in truncated if unicodedata.category(c) not in ("Cc", "Cf"))


# ---------------------------------------------------------------------------
# Third-party headline sanitization (F3 — indirect prompt injection)
# ---------------------------------------------------------------------------

HEADLINE_MAX_LEN = 200


_EQUALS_RUN_RE = re.compile(r"={2,}")


_LEADING_MARKER_RE = re.compile(r"^(?:[-*•#=]+\s+)+")


def sanitize_headline(headline: str, *, max_len: int = HEADLINE_MAX_LEN) -> str:
    """Neutralize a third-party news headline for safe prompt interpolation.

    Headlines are fetched from remote RSS/Atom feeds (Google News, Yahoo
    Finance), i.e. authored by anyone who can get a title published, and are
    rendered into the market-context block every agent sees. A title must
    therefore never be able to forge prompt structure or smuggle instructions.

    Applies the same Cc/Cf stripping rule as sanitize_entity_name(), plus the
    extra guarantees the market-context template needs:

    - Cc, Cf, Zl and Zp characters (CR, LF, TAB, U+2028, U+2029, zero-width
      and bidi format characters) become a single space, so one headline can
      never span more than one rendered line. They become spaces rather than
      being dropped so that "foo\\nbar" reads "foo bar", not "foobar".
    - '<' and '>' become spaces, so a headline cannot close or reopen the
      untrusted-data fence that worker.py wraps the block in.
    - Runs of '=' collapse to a single '=', so a headline cannot forge an
      "== ENTITY ==" block header.
    - Leading bullet/heading markers are dropped, so a headline cannot pose
      as an additional "  - " list item or a markdown heading.
    - Whitespace runs collapse to one space; the result is hard-capped at
      max_len characters with a trailing ellipsis marking truncation.

    Idempotent: sanitizing an already-sanitized headline returns it unchanged.
    Returns "" when nothing survives — callers must skip empty results.
    """
    cleaned = "".join(
        " " if (c in "<>" or unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp")) else c for c in headline
    )
    cleaned = " ".join(cleaned.split())  # collapse whitespace runs, strip ends
    cleaned = _EQUALS_RUN_RE.sub("=", cleaned)
    cleaned = _LEADING_MARKER_RE.sub("", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


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
# invisible tag characters included) becomes a space, the rule sanitize_headline
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
