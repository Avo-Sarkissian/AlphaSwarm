"""Display glyphs live in report templates, not in graph read rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "alphaswarm" / "templates" / "report"


@pytest.fixture()
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )


def test_shock_arrow_macro_renders_every_sign(env: Environment) -> None:
    shock_arrow = env.get_template("_macros.j2").module.shock_arrow

    assert [str(shock_arrow(d)) for d in (12.5, 0.01, -0.01, -50.0, 0.0, -0.0)] == [
        "▲",
        "▲",
        "▼",
        "▼",
        "·",
        "·",
    ]


def test_shock_template_reads_no_glyph_key() -> None:
    source = (TEMPLATES / "11_shock_impact.j2").read_text(encoding="utf-8")

    assert "dominant_arrow" not in source
    assert '{% from "_macros.j2" import shock_arrow %}' in source
