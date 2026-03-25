"""CLI entry point for AlphaSwarm with subcommand routing.

Usage:
    python -m alphaswarm                  # Print startup banner (legacy)
    python -m alphaswarm inject "rumor"   # Inject a seed rumor
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

import structlog

from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs

if TYPE_CHECKING:
    from alphaswarm.types import ParsedSeedResult

logger = structlog.get_logger(component="cli")

BANNER = """
============================================================
  AlphaSwarm v{version}
  Agents: {agents} across {brackets} brackets
  Orchestrator: {orchestrator}
  Workers: {worker}
============================================================
""".strip()


def _print_banner() -> None:
    """Load settings, brackets, personas and print the startup banner."""
    try:
        settings = AppSettings()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    brackets = load_bracket_configs()
    personas = generate_personas(brackets)

    print(BANNER.format(
        version="0.1.0",
        agents=len(personas),
        brackets=len(brackets),
        orchestrator=settings.ollama.orchestrator_model,
        worker=settings.ollama.worker_model,
    ))


def _print_injection_summary(cycle_id: str, parsed_result: ParsedSeedResult) -> None:
    """Print a formatted summary of the seed injection result."""
    from alphaswarm.types import ParsedSeedResult as _ParsedSeedResult  # noqa: F811

    seed_event = parsed_result.seed_event
    tier_labels = {1: "direct JSON", 2: "extracted/cleaned", 3: "FALLBACK (parse failed)"}
    tier_label = tier_labels.get(parsed_result.parse_tier, "unknown")

    print(f"\n{'='*60}")
    print("  Seed Injection Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID:          {cycle_id}")
    print(f"  Overall Sentiment: {seed_event.overall_sentiment:+.2f}")
    print(f"  Parse Quality:     Tier {parsed_result.parse_tier} ({tier_label})")
    print(f"  Entities:          {len(seed_event.entities)}")

    if seed_event.entities:
        print(f"\n  {'Name':<25} {'Type':<10} {'Relevance':>10} {'Sentiment':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for entity in seed_event.entities:
            print(
                f"  {entity.name:<25} {entity.type.value:<10} "
                f"{entity.relevance:>10.2f} {entity.sentiment:>+10.2f}"
            )

    print(f"{'='*60}\n")


async def _handle_inject(rumor: str) -> None:
    """Run seed injection pipeline and print summary.

    Lifecycle:
    1. Create AppState with Ollama + Neo4j
    2. ensure_schema() for idempotent schema setup
    3. inject_seed() for orchestrator parse + atomic persist
    4. Print structured summary
    5. Close Neo4j driver in finally block
    """
    from alphaswarm.app import create_app_state
    from alphaswarm.seed import inject_seed

    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)

    assert app.ollama_client is not None
    assert app.model_manager is not None
    assert app.graph_manager is not None

    try:
        # Ensure schema is applied (explicit in inject path)
        await app.graph_manager.ensure_schema()

        cycle_id, parsed_result = await inject_seed(
            rumor=rumor,
            settings=settings,
            ollama_client=app.ollama_client,
            model_manager=app.model_manager,
            graph_manager=app.graph_manager,
        )
        _print_injection_summary(cycle_id, parsed_result)
    finally:
        # Close Neo4j driver
        await app.graph_manager.close()


def main() -> None:
    """CLI entry point with argparse subcommand routing."""
    parser = argparse.ArgumentParser(
        prog="alphaswarm",
        description="AlphaSwarm: Multi-agent financial simulation engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    inject_parser = subparsers.add_parser("inject", help="Inject a seed rumor")
    inject_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")

    args = parser.parse_args()

    if args.command == "inject":
        try:
            asyncio.run(_handle_inject(args.rumor))
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("inject_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        _print_banner()
