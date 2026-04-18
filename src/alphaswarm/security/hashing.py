"""Shared correlation hash helpers.

sha256_first8 is consumed by:
  - PII redaction processor (Plan 03, D-06: account_* key handling)
  - HoldingsLoader (Phase 39, HOLD-02: raw account numbers hashed before storage)

Truncation to 8 hex chars is acceptable for correlation (not authentication).
See research assumption A4 for collision-risk analysis.
"""

from __future__ import annotations

import hashlib


def sha256_first8(value: str) -> str:
    """Return the first 8 hex characters of SHA256(value).

    Raises:
        TypeError: if value is None or empty string (Pitfall 7 — prevents
            all redacted values collapsing to the hash of empty string).
    """
    if not isinstance(value, str):
        raise TypeError(f"sha256_first8 requires str, got {type(value).__name__}")
    if value == "":
        raise TypeError("sha256_first8 requires non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
