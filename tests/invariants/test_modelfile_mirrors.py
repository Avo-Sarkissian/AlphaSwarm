"""Settings and constants that mirror Modelfile parameters stay in sync with them."""

from __future__ import annotations

import re

from alphaswarm.settings import PROJECT_ROOT, OllamaSettings

MODELFILES = PROJECT_ROOT / "modelfiles"


def modelfile_parameter(modelfile: str, name: str) -> int:
    text = (MODELFILES / modelfile).read_text(encoding="utf-8")
    match = re.search(rf"^PARAMETER {name} (\d+)\s*$", text, re.MULTILINE)
    assert match is not None, f"{modelfile} has no PARAMETER {name}"
    return int(match.group(1))


def test_worker_num_ctx_setting_mirrors_the_modelfile() -> None:
    assert OllamaSettings().worker_num_ctx == modelfile_parameter("Modelfile.worker", "num_ctx")
