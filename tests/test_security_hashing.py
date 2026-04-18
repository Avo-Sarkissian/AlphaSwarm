"""Unit tests for sha256_first8 — shared correlation hasher.

Consumed by the PII redaction processor (Plan 03) and HoldingsLoader (Phase 39).
"""

from __future__ import annotations

import re

import pytest

from alphaswarm.security.hashing import sha256_first8


def test_sha256_first8_returns_8_hex_chars() -> None:
    result = sha256_first8("account_12345")
    assert re.fullmatch(r"[0-9a-f]{8}", result) is not None


def test_sha256_first8_is_deterministic() -> None:
    assert sha256_first8("same_input") == sha256_first8("same_input")


def test_sha256_first8_distinct_inputs_give_distinct_outputs() -> None:
    a = sha256_first8("account_1")
    b = sha256_first8("account_2")
    assert a != b


def test_sha256_first8_rejects_empty_string() -> None:
    with pytest.raises(TypeError):
        sha256_first8("")


def test_sha256_first8_rejects_none() -> None:
    with pytest.raises(TypeError):
        sha256_first8(None)  # type: ignore[arg-type]


def test_sha256_first8_rejects_non_str_inputs() -> None:
    with pytest.raises(TypeError):
        sha256_first8(12345)  # type: ignore[arg-type]
