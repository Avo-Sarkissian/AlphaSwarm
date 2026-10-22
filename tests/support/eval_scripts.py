"""Load the repo-root eval/ scripts by path; they are scripts, not a package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

EVAL_DIR: Final = Path(__file__).resolve().parents[2] / "eval"


def load_eval_script(name: str) -> ModuleType:
    """Import ``eval/<name>.py`` under a private module name.

    The module is registered in ``sys.modules`` so pydantic and dataclasses can resolve it.
    """
    path = EVAL_DIR / f"{name}.py"
    module_name = f"eval_script_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
