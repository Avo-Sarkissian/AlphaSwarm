"""The prompt-template hash identifies the static persona prompt set."""

from __future__ import annotations

import re

from alphaswarm.config import compute_prompt_template_hash, load_bracket_configs


def test_hash_is_stable_sha256_hex() -> None:
    first = compute_prompt_template_hash(load_bracket_configs())

    assert first == compute_prompt_template_hash(load_bracket_configs())
    assert re.fullmatch(r"[0-9a-f]{64}", first)


def test_hash_changes_when_a_template_changes() -> None:
    brackets = load_bracket_configs()
    changed = [
        brackets[0].model_copy(
            update={"system_prompt_template": brackets[0].system_prompt_template + " x"},
        ),
        *brackets[1:],
    ]

    assert compute_prompt_template_hash(changed) != compute_prompt_template_hash(brackets)


def test_hash_depends_on_bracket_order() -> None:
    brackets = load_bracket_configs()

    assert compute_prompt_template_hash(list(reversed(brackets))) != compute_prompt_template_hash(
        brackets,
    )
