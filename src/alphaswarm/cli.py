"""CLI entry point for AlphaSwarm with subcommand routing.

Usage:
    python -m alphaswarm                  # Print startup banner (legacy)
    python -m alphaswarm inject "rumor"   # Inject a seed rumor
    python -m alphaswarm run "rumor"      # Run a full simulation (ALPHASWARM_NUM_ROUNDS)
    python -m alphaswarm run "rumor" --context-fixture PATH  # point-in-time market block
    python -m alphaswarm run "rumor" --no-market-context     # no market block, no live fetch
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from alphaswarm import __version__
from alphaswarm.fsutil import atomic_write_text
from alphaswarm.ingestion.fixture import load_context_fixture
from alphaswarm.logging import configure_logging
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.readiness import NEO4J_FIX
from alphaswarm.services.runtime import close_operation, open_runtime, open_simulation
from alphaswarm.settings import AppSettings
from alphaswarm.simulation import run_simulation
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ingestion.types import ContextPacket
    from alphaswarm.rounds import RoundCompleteEvent, ShiftMetrics
    from alphaswarm.services.runtime import Runtime
    from alphaswarm.simulation import SimulationResult
    from alphaswarm.state import BracketSummary
    from alphaswarm.types import AgentDecision, AgentPersona, BracketConfig, ParsedSeedResult

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

    print(
        BANNER.format(
            version=__version__,
            agents=len(personas),
            brackets=len(brackets),
            orchestrator=settings.ollama.orchestrator_model,
            worker=settings.ollama.worker_model,
        )
    )


def _print_injection_summary(cycle_id: str, parsed_result: ParsedSeedResult) -> None:
    """Print a formatted summary of the seed injection result."""

    seed_event = parsed_result.seed_event
    tier_labels = {1: "direct JSON", 2: "extracted/cleaned", 3: "FALLBACK (parse failed)"}
    tier_label = tier_labels.get(parsed_result.parse_tier, "unknown")

    print(f"\n{'=' * 60}")
    print("  Seed Injection Complete")
    print(f"{'=' * 60}")
    print(f"  Cycle ID:          {cycle_id}")
    print(f"  Overall Sentiment: {seed_event.overall_sentiment:+.2f}")
    print(f"  Parse Quality:     Tier {parsed_result.parse_tier} ({tier_label})")
    print(f"  Entities:          {len(seed_event.entities)}")

    if seed_event.entities:
        print(f"\n  {'Name':<25} {'Type':<10} {'Relevance':>10} {'Sentiment':>10}")
        print(f"  {'-' * 25} {'-' * 10} {'-' * 10} {'-' * 10}")
        for entity in seed_event.entities:
            print(f"  {entity.name:<25} {entity.type.value:<10} {entity.relevance:>10.2f} {entity.sentiment:>+10.2f}")

    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Rationale sanitization (review concern #8)
# ---------------------------------------------------------------------------


def _sanitize_rationale(text: str, max_len: int = 80) -> str:
    """Strip control characters, normalize whitespace, truncate.

    Delegates to alphaswarm.security.sanitize.sanitize_rationale (shared utility).
    """
    from alphaswarm.security.sanitize import sanitize_rationale

    return sanitize_rationale(text, max_len)


# ---------------------------------------------------------------------------
# Generalized round report (Phase 7)
# ---------------------------------------------------------------------------


def _print_bracket_table_from_summaries(
    summaries: tuple[BracketSummary, ...],
) -> None:
    """Print bracket signal distribution from BracketSummary (D-08)."""
    if not summaries:
        return
    print(f"\n  {'Bracket':<15} {'BUY':>5} {'SELL':>5} {'HOLD':>5} {'Avg Conf':>10}")
    print(f"  {'-' * 15} {'-' * 5} {'-' * 5} {'-' * 5} {'-' * 10}")
    for s in summaries:
        print(f"  {s.display_name:<15} {s.buy_count:>5} {s.sell_count:>5} {s.hold_count:>5} {s.avg_confidence:>10.2f}")


def _print_round_report(
    round_num: int,
    cycle_id: str,
    agent_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
    *,
    bracket_summaries: tuple[BracketSummary, ...] | None = None,
) -> None:
    """Print bracket signal distribution and notable decisions for any round.

    Matches the UI-SPEC visual contract:
    ============================================================
      Round {N} Complete
    ============================================================
      Cycle ID: {cycle_id}
      Agents:   {success}/{total} ({errors} PARSE_ERROR)

    When bracket_summaries is provided (Phase 8+), renders from summaries.
    Otherwise computes them with rounds.compute_bracket_summaries().
    Handles all-PARSE_ERROR edge case with warning (Codex review).
    """
    all_decisions = [d for _, d in agent_decisions]
    total = len(all_decisions)
    errors = sum(1 for d in all_decisions if d.signal == SignalType.PARSE_ERROR)
    success = total - errors

    print(f"\n{'=' * 60}")
    print(f"  Round {round_num} Complete")
    print(f"{'=' * 60}")
    print(f"  Cycle ID: {cycle_id}")
    if errors > 0:
        print(f"  Agents:   {success}/{total} ({errors} PARSE_ERROR)")
    else:
        print(f"  Agents:   {total}/{total}")

    # All-PARSE_ERROR edge case (Codex review / UI-SPEC empty state)
    if success == 0:
        print(f"  Warning: All {total} agents returned PARSE_ERROR. No valid decisions to report.")
        print(f"{'=' * 60}\n")
        return

    # Bracket summary table: use promoted BracketSummary if available (D-08)
    if bracket_summaries is not None:
        _print_bracket_table_from_summaries(bracket_summaries)
    else:
        from alphaswarm.rounds import compute_bracket_summaries

        _print_bracket_table_from_summaries(compute_bracket_summaries(agent_decisions, personas, brackets))

    # Notable Decisions (top 5 by confidence, excluding PARSE_ERROR)
    valid = [(aid, d) for aid, d in agent_decisions if d.signal != SignalType.PARSE_ERROR]
    top5 = sorted(valid, key=lambda x: x[1].confidence, reverse=True)[:5]
    print("\n  Notable Decisions (Top 5 by Confidence)")
    print(f"  {'-' * 55}")
    for agent_id, decision in top5:
        snippet = _sanitize_rationale(decision.rationale, max_len=80)
        print(f"  {agent_id:<20} {decision.signal.value.upper():<5} {decision.confidence:.2f}  {snippet}")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Shift analysis (Phase 7)
# ---------------------------------------------------------------------------


def _print_shift_analysis(
    shift: ShiftMetrics,
    prev_round: int,
    curr_round: int,
    *,
    agent_count: int,
) -> None:
    """Print signal transition counts and per-bracket confidence drift.

    Per UI-SPEC: transition pairs in two columns, bracket delta with sign prefix.
    When no agents shifted, prints a single-line message instead of empty table.

    ShiftMetrics uses tuple fields for immutability. Convert to dict for lookup.
    """
    transitions = dict(shift.signal_transitions)

    print(f"  Signal Transitions (Round {prev_round} -> Round {curr_round})")
    print(f"  {'-' * 40}")

    if shift.total_flips == 0:
        print("  No agents changed signal between rounds.")
    else:
        pairs = [
            ("BUY->SELL", "SELL->BUY"),
            ("BUY->HOLD", "SELL->HOLD"),
            ("HOLD->BUY", "HOLD->SELL"),
        ]
        for left_key, right_key in pairs:
            left_count = transitions.get(left_key, 0)
            right_count = transitions.get(right_key, 0)
            left_str = f"  {left_key}: {left_count:>2}"
            right_str = f"{right_key}: {right_count:>2}"
            print(f"{left_str}      {right_str}")
        print(f"  Total agents shifted: {shift.agents_shifted}/{agent_count}")

    bracket_deltas = dict(shift.bracket_confidence_delta)
    if bracket_deltas:
        print("\n  Confidence Drift by Bracket")
        print(f"  {'-' * 40}")
        for bracket, delta in bracket_deltas.items():
            sign = "+" if delta >= 0 else ""
            print(f"  {bracket:<15} {sign}{delta:.2f}")

    print()


# ---------------------------------------------------------------------------
# Simulation summary (Phase 7)
# ---------------------------------------------------------------------------


def _print_simulation_summary(
    result: SimulationResult,
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
    *,
    num_rounds: int,
) -> None:
    """Print the final summary from the last round that ran.

    Convergence compares R1->R2 with R2->R3 flips, so it is only reported for
    3-round runs (docs/DECISIONS.md#adr-num-rounds).
    """
    from alphaswarm.rounds import compute_bracket_summaries

    final_round = 3 if num_rounds >= 3 else 2
    r2_flips = result.round2_shifts.total_flips
    if final_round == 3:
        r3_flips = result.round3_shifts.total_flips
        flips_line = f"{r2_flips} (R1->R2) + {r3_flips} (R2->R3) = {r2_flips + r3_flips} total"
        if r3_flips < r2_flips:
            convergence = "Yes (flips decreased between rounds)"
        elif r3_flips > r2_flips:
            convergence = "No (flips increased between rounds)"
        else:
            convergence = "No (flips unchanged between rounds)"
        final_decisions = result.round3_decisions
        final_summaries = result.round3_summaries
    else:
        flips_line = f"{r2_flips} (R1->R2) = {r2_flips} total"
        convergence = "n/a (needs 3 rounds)"
        final_decisions = result.round2_decisions
        final_summaries = result.round2_summaries

    print(f"{'=' * 60}")
    print("  Simulation Complete")
    print(f"{'=' * 60}")
    print(f"  Cycle ID:       {result.cycle_id}")
    print(f"  Total Rounds:   {final_round}")
    print(f"  Signal Flips:   {flips_line}")
    print(f"  Convergence:    {convergence}")
    print(f"\n  Final Consensus Distribution (Round {final_round})")
    print(f"  {'-' * 40}")
    summaries = final_summaries or compute_bracket_summaries(final_decisions, personas, brackets)
    _print_bracket_table_from_summaries(summaries)
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Progressive output callback factory (Phase 7)
# ---------------------------------------------------------------------------


def _make_round_complete_handler(
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
) -> Callable[[RoundCompleteEvent], Awaitable[None]]:
    """Create an on_round_complete callback for progressive CLI output.

    Addresses Gemini MEDIUM / Codex HIGH review concern: reports MUST print
    as each round finishes, not after run_simulation() returns.

    The returned async function is passed to run_simulation(on_round_complete=handler).
    It prints:
    - Round N bracket table + notable decisions (for all rounds)
    - Shift analysis (for Rounds 2 and 3 only, when event.shift is not None)
    """

    async def handler(event: RoundCompleteEvent) -> None:
        _print_round_report(
            event.round_num,
            event.cycle_id,
            event.agent_decisions,
            personas,
            brackets,
            bracket_summaries=event.bracket_summaries,
        )
        if event.shift is not None:
            _print_shift_analysis(
                event.shift,
                event.round_num - 1,
                event.round_num,
                agent_count=len(personas),
            )

    return handler


# ---------------------------------------------------------------------------
# Subcommand handlers: each one enters the shared runtime (open_runtime)
# ---------------------------------------------------------------------------


def _require_graph(runtime: Runtime) -> GraphStateManager:
    """The graph manager, or an error message and exit code 1 when Neo4j is unreachable."""
    graph = runtime.app_state.graph_manager
    if graph is None or not runtime.neo4j_ready:
        print(
            f"Error: Neo4j is not reachable. {NEO4J_FIX}; if it runs, check ALPHASWARM_NEO4J__PASSWORD in .env.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return graph


async def _run_pipeline(
    rumor: str,
    settings: AppSettings,
    *,
    context_fixture: ContextPacket | None = None,
    market_context: bool = True,
) -> None:
    """Full simulation from the CLI through the shared runtime (docs/DECISIONS.md#p7-d-17).

    Reports print as each round completes (docs/DECISIONS.md#p7-d-14). The market
    and news providers come from build_runtime, as on the web
    (docs/DECISIONS.md#p40-d-10); a context fixture or ``market_context=False``
    keeps them out of the run, so nothing is fetched
    (docs/DECISIONS.md#adr-eval-harness).
    """
    async with open_runtime(settings) as runtime:
        _require_graph(runtime)
        personas = list(runtime.app_state.personas)
        brackets = load_bracket_configs()
        cfg = await runtime.inference.config()
        print(
            f"Inference mode: {await runtime.inference.mode()} "
            f"(orchestrator={cfg.orchestrator.model}, worker={cfg.worker.model})"
        )
        print(f"Starting {settings.num_rounds}-round simulation...")
        handler = _make_round_complete_handler(personas, brackets)
        async with open_simulation(
            runtime.inference,
            runtime.app_state,
            state=runtime.app_state.state_store,
        ) as deps:
            if context_fixture is not None or not market_context:
                deps = dataclasses.replace(deps, market=None, news=None, context_fixture=context_fixture)
            result = await run_simulation(rumor, deps, personas, brackets, on_round_complete=handler)
        _print_simulation_summary(result, personas, brackets, num_rounds=settings.num_rounds)


def _handle_run(
    rumor: str,
    *,
    context_fixture: ContextPacket | None = None,
    market_context: bool = True,
) -> None:
    """Synchronous entry for ``alphaswarm run``: the runtime is built inside the loop."""
    asyncio.run(
        _run_pipeline(rumor, AppSettings(), context_fixture=context_fixture, market_context=market_context),
    )


async def _handle_inject(rumor: str) -> None:
    """Parse and persist a seed rumor, then print the summary (schema applied by open_runtime).

    No run follows an inject, so the seed-only Cycle is marked failed: it must
    not stay ``running`` (docs/DECISIONS.md#adr-cycle-metrics).
    """
    from alphaswarm.seed import inject_seed

    settings = AppSettings()
    async with open_runtime(settings) as runtime:
        graph = _require_graph(runtime)
        built = await runtime.inference.open_operation("inject")
        try:
            cycle_id, parsed_result, _modifier_result = await inject_seed(
                rumor=rumor,
                settings=settings,
                orchestrator=built.orchestrator,
                graph_manager=graph,
            )
        finally:
            # inject_seed tears the model down itself (docs/DECISIONS.md#p5-d-07).
            await close_operation(built, teardown=False)
        _print_injection_summary(cycle_id, parsed_result)
        # The status the back-fill gives a legacy seed-only cycle.
        await graph.set_cycle_status(cycle_id, "failed")


async def _handle_report(cycle_id: str | None, output: str | None) -> None:
    """``alphaswarm report``: one ReportService run; default = the latest complete cycle.

    The service prepares and tears down the orchestrator around the one
    narrative call (docs/DECISIONS.md#p15-d-12) and writes the markdown plus
    its sections sidecar to the reports directory; ``--output`` also writes a
    copy of the markdown there.
    """
    from alphaswarm.services.report import ReportService

    settings = AppSettings()
    async with open_runtime(settings) as runtime:
        graph = _require_graph(runtime)
        if cycle_id is None:
            cycle_id = await graph.read_latest_cycle_id()
            if cycle_id is None:
                print("Error: No complete simulation cycles found in the database.", file=sys.stderr)
                raise SystemExit(1)
        print(
            "WARNING: Report generation uses the orchestrator model. "
            "Do not run concurrently with simulations or interviews."
        )
        service = ReportService(
            graph=graph,
            inference=runtime.inference,
            jobs=runtime.jobs,
            reports_dir=settings.resolve_path(settings.reports_dir),
        )
        result = await service.generate(cycle_id)
    output_path = result.path
    if output is not None:
        output_path = Path(output).expanduser()
        await asyncio.to_thread(atomic_write_text, output_path, result.content, mode=0o644)
    print(f"Report generated: {output_path}")


# ---------------------------------------------------------------------------
# Web server handler
# ---------------------------------------------------------------------------


def _handle_web(host: str, port: int) -> None:
    """Start the web server: the single documented launcher (docs/DECISIONS.md#adr-web-lifespan).

    uvicorn imports ``alphaswarm.web.app:create_app`` and calls it in its own
    event loop (factory mode), so nothing is built at import time; ``workers=1``
    because every piece of state lives in one process. ``start`` calls this same
    function. Logging is configured before uvicorn starts and uvicorn gets
    ``log_config=None``, so even its first lines go through the redacting
    structlog bridge; the lifespan's ``open_runtime`` configures it again
    (idempotent) (docs/DECISIONS.md#adr-security-2026-08).
    """
    import uvicorn

    settings = AppSettings()
    configure_logging(log_level=settings.log_level, json_output=not settings.debug)
    uvicorn.run(
        "alphaswarm.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=1,
        log_config=None,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _context_fixture_arg(value: str) -> ContextPacket:
    """argparse type for ``--context-fixture``: a validated point-in-time ContextPacket.

    Loading here means a bad fixture is a usage error (exit 2) before any runtime,
    model or database is touched (docs/DECISIONS.md#adr-eval-harness).
    """
    try:
        return load_context_fixture(Path(value).expanduser())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> None:
    """CLI entry point with argparse subcommand routing."""
    parser = argparse.ArgumentParser(
        prog="alphaswarm",
        description="AlphaSwarm: Multi-agent financial simulation engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    inject_parser = subparsers.add_parser("inject", help="Inject a seed rumor")
    inject_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")

    run_parser = subparsers.add_parser("run", help="Run a full simulation (ALPHASWARM_NUM_ROUNDS=2|3 rounds)")
    run_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")
    context = run_parser.add_mutually_exclusive_group()
    context.add_argument(
        "--context-fixture",
        type=_context_fixture_arg,
        default=None,
        metavar="PATH",
        help="point-in-time ContextPacket JSON used as the market block (no live fetches)",
    )
    context.add_argument(
        "--no-market-context",
        action="store_true",
        help="send no market block at all (no live fetches)",
    )

    report_parser = subparsers.add_parser("report", help="Generate post-simulation analysis report")
    report_parser.add_argument(
        "--cycle",
        type=str,
        default=None,
        help="Cycle ID to report on (defaults to the most recent complete cycle)",
    )
    report_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Also write the markdown to this path",
    )

    web_parser = subparsers.add_parser("web", help="Start web UI server")
    web_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number (default: 8000)",
    )

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
    elif args.command == "run":
        try:
            run_kwargs: dict[str, Any] = {}
            if args.context_fixture is not None:
                run_kwargs["context_fixture"] = args.context_fixture
            elif args.no_market_context:
                run_kwargs["market_context"] = False
            _handle_run(args.rumor, **run_kwargs)
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("run_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "report":
        try:
            asyncio.run(_handle_report(args.cycle, args.output))
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("report_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "web":
        try:
            _handle_web(args.host, args.port)
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("web_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        _print_banner()


def main_web() -> None:
    """Direct entry point for 'start' console script — launches the web UI.

    Replaces main_tui: the TUI was retired by the v5.0 web-first decision.
    """
    try:
        _handle_web("127.0.0.1", 8000)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error("web_failed", error=str(e))
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
