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
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text)
    cleaned = ' '.join(cleaned.split())
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned
