"""Fakes and helpers for code that talks to GraphStateManager.

Shared by the engine scenarios (tests/engine/conftest.py), tests/test_simulation.py
and the seeded-cycle builder. Values are fictional.
"""

from __future__ import annotations

from typing import Final

from alphaswarm.episodes import EntityRef

SCENARIO_ENTITIES: Final[tuple[EntityRef, ...]] = (
    EntityRef("ZZZT Holdings", "company"),
    EntityRef("QQQX Robotics", "company"),
    EntityRef("Industrial Automation", "sector"),
)
