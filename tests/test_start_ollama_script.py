"""scripts/start_ollama.sh starts Ollama with the MLX backend (docs/RUNBOOK.md section 1).

Without OLLAMA_USE_MLX=1 the nvfp4 models silently fall back to llama.cpp:
2.8x slower worker prefill, 30x slower orchestrator prefill. A fake `ollama`
on PATH records the environment it was started with.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start_ollama.sh"


def _start(tmp_path: Path, **env_overrides: str) -> dict[str, str]:
    fake_ollama = tmp_path / "ollama"
    fake_ollama.write_text(
        "#!/usr/bin/env bash\necho \"ARGS=$*\"\nenv | grep '^OLLAMA_' | sort\n",
        encoding="utf-8",
    )
    fake_ollama.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path), **env_overrides}
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
    pairs = (line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    return {key: value for key, value in pairs}


def test_mlx_backend_is_enabled_by_default(tmp_path: Path) -> None:
    seen = _start(tmp_path)
    assert seen["ARGS"] == "serve"
    assert seen["OLLAMA_USE_MLX"] == "1"
    assert seen["OLLAMA_NUM_PARALLEL"] == "4"
    assert seen["OLLAMA_MAX_LOADED_MODELS"] == "2"


def test_an_explicit_value_from_the_caller_wins(tmp_path: Path) -> None:
    seen = _start(tmp_path, OLLAMA_USE_MLX="0")
    assert seen["OLLAMA_USE_MLX"] == "0"
