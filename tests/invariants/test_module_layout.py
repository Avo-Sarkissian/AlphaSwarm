"""Where each name lives after the config split."""

from __future__ import annotations


def test_worker_persona_config_is_a_domain_type() -> None:
    from alphaswarm import types

    assert types.WorkerPersonaConfig.__module__ == "alphaswarm.types"
