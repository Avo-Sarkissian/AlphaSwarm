"""AlphaSwarm entry point. Run via: uv run python -m alphaswarm"""

import sys

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs


BANNER = """
============================================================
  AlphaSwarm v{version}
  Agents: {agents} across {brackets} brackets
  Orchestrator: {orchestrator}
  Workers: {worker}
============================================================
""".strip()


def main() -> None:
    """Application entry point. Validates config and prints startup banner."""
    try:
        settings = AppSettings()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app_state = create_app_state(settings, personas)

    app_state.logger.info(
        "alphaswarm started",
        version="0.1.0",
        agents_total=len(personas),
        brackets_total=len(brackets),
        orchestrator_model=settings.ollama.orchestrator_model,
        worker_model=settings.ollama.worker_model,
    )

    print(BANNER.format(
        version="0.1.0",
        agents=len(personas),
        brackets=len(brackets),
        orchestrator=settings.ollama.orchestrator_model,
        worker=settings.ollama.worker_model,
    ))


if __name__ == "__main__":
    main()
