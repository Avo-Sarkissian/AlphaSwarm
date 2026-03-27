"""CLI entry point for AlphaSwarm with subcommand routing.

Usage:
    python -m alphaswarm                  # Print startup banner (legacy)
    python -m alphaswarm inject "rumor"   # Inject a seed rumor
    python -m alphaswarm run "rumor"      # Run full 3-round simulation
    python -m alphaswarm tui "rumor"      # Launch TUI dashboard with live simulation
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.simulation import (
        BracketSummary,
        RoundCompleteEvent,
        Round1Result,
        ShiftMetrics,
        SimulationResult,
    )
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


# ---------------------------------------------------------------------------
# Rationale sanitization (review concern #8)
# ---------------------------------------------------------------------------


def _sanitize_rationale(text: str, max_len: int = 80) -> str:
    """Strip control characters, normalize whitespace, truncate.

    Delegates to alphaswarm.utils.sanitize_rationale (shared utility).
    """
    from alphaswarm.utils import sanitize_rationale
    return sanitize_rationale(text, max_len)


# ---------------------------------------------------------------------------
# Bracket aggregation
# ---------------------------------------------------------------------------


def _aggregate_brackets(
    agent_decisions: list[tuple[str, AgentDecision]],
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
) -> dict[str, dict[str, int | float]]:
    """Compute bracket aggregation inline (pre-Phase 8 path).

    NOTE: For Phase 8+ simulation results, use BracketSummary from
    SimulationResult/RoundCompleteEvent instead. This function is retained
    for backward compatibility with the inject CLI path and Round 1 standalone.
    If modifying aggregation logic, update compute_bracket_summaries() in
    simulation.py as the authoritative source.

    Excludes PARSE_ERROR agents from signal counts and confidence averages.

    Returns:
        Dict keyed by bracket display_name, each containing:
        BUY, SELL, HOLD counts, total count, and avg_conf.
    """
    # Build lookups
    agent_bracket: dict[str, str] = {p.id: p.bracket.value for p in personas}
    display_lookup: dict[str, str] = {b.bracket_type.value: b.display_name for b in brackets}

    # Initialize per-bracket counters (preserve bracket order)
    result: dict[str, dict[str, int | float]] = {}
    for b in brackets:
        result[b.display_name] = {
            "BUY": 0,
            "SELL": 0,
            "HOLD": 0,
            "total": 0,
            "confidence_sum": 0.0,
            "avg_conf": 0.0,
        }

    # Aggregate
    for agent_id, decision in agent_decisions:
        if decision.signal == SignalType.PARSE_ERROR:
            continue
        bracket_value = agent_bracket.get(agent_id)
        if bracket_value is None:
            continue
        display_name = display_lookup.get(bracket_value)
        if display_name is None:
            continue
        entry = result[display_name]
        signal_key = decision.signal.value.upper()
        if signal_key in entry:
            entry[signal_key] = int(entry[signal_key]) + 1
        entry["total"] = int(entry["total"]) + 1
        entry["confidence_sum"] = float(entry["confidence_sum"]) + decision.confidence

    # Compute averages
    for data in result.values():
        total = int(data["total"])
        if total > 0:
            data["avg_conf"] = float(data["confidence_sum"]) / total
        else:
            data["avg_conf"] = 0.0

    return result


# ---------------------------------------------------------------------------
# Round 1 report
# ---------------------------------------------------------------------------


def _print_round1_report(
    result: Round1Result,
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
) -> None:
    """Print bracket signal distribution and notable decisions after Round 1."""
    # Derive decisions from single canonical collection
    all_decisions = [d for _, d in result.agent_decisions]
    total = len(all_decisions)
    errors = sum(1 for d in all_decisions if d.signal == SignalType.PARSE_ERROR)
    success = total - errors

    # Header
    print(f"\n{'='*60}")
    print("  Round 1 Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID: {result.cycle_id}")
    if errors > 0:
        print(f"  Agents:   {success}/{total} ({errors} PARSE_ERROR)")
    else:
        print(f"  Agents:   {total}/{total}")

    # Bracket summary table
    bracket_data = _aggregate_brackets(result.agent_decisions, personas, brackets)
    print(f"\n  {'Bracket':<15} {'BUY':>5} {'SELL':>5} {'HOLD':>5} {'Avg Conf':>10}")
    print(f"  {'-'*15} {'-'*5} {'-'*5} {'-'*5} {'-'*10}")
    for name, data in bracket_data.items():
        print(
            f"  {name:<15} {data['BUY']:>5} {data['SELL']:>5} "
            f"{data['HOLD']:>5} {data['avg_conf']:>10.2f}"
        )

    # Notable Decisions (top 5 by confidence, excluding PARSE_ERROR)
    valid = [
        (aid, d) for aid, d in result.agent_decisions
        if d.signal != SignalType.PARSE_ERROR
    ]
    top5 = sorted(valid, key=lambda x: x[1].confidence, reverse=True)[:5]
    print(f"\n  Notable Decisions (Top 5 by Confidence)")
    print(f"  {'-'*55}")
    for agent_id, decision in top5:
        snippet = _sanitize_rationale(decision.rationale, max_len=80)
        print(
            f"  {agent_id:<20} {decision.signal.value.upper():<5} "
            f"{decision.confidence:.2f}  {snippet}"
        )
    print(f"{'='*60}\n")


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
    print(f"  {'-'*15} {'-'*5} {'-'*5} {'-'*5} {'-'*10}")
    for s in summaries:
        print(
            f"  {s.display_name:<15} {s.buy_count:>5} {s.sell_count:>5} "
            f"{s.hold_count:>5} {s.avg_confidence:>10.2f}"
        )


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
    Otherwise falls back to inline _aggregate_brackets() computation.
    Handles all-PARSE_ERROR edge case with warning (Codex review).
    """
    all_decisions = [d for _, d in agent_decisions]
    total = len(all_decisions)
    errors = sum(1 for d in all_decisions if d.signal == SignalType.PARSE_ERROR)
    success = total - errors

    print(f"\n{'='*60}")
    print(f"  Round {round_num} Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID: {cycle_id}")
    if errors > 0:
        print(f"  Agents:   {success}/{total} ({errors} PARSE_ERROR)")
    else:
        print(f"  Agents:   {total}/{total}")

    # All-PARSE_ERROR edge case (Codex review / UI-SPEC empty state)
    if success == 0:
        print(f"  Warning: All {total} agents returned PARSE_ERROR. No valid decisions to report.")
        print(f"{'='*60}\n")
        return

    # Bracket summary table: use promoted BracketSummary if available (D-08)
    if bracket_summaries is not None:
        _print_bracket_table_from_summaries(bracket_summaries)
    else:
        # Fallback: compute inline (pre-Phase 8 path)
        decisions_list = list(agent_decisions)
        bracket_data = _aggregate_brackets(decisions_list, personas, brackets)
        print(f"\n  {'Bracket':<15} {'BUY':>5} {'SELL':>5} {'HOLD':>5} {'Avg Conf':>10}")
        print(f"  {'-'*15} {'-'*5} {'-'*5} {'-'*5} {'-'*10}")
        for name, data in bracket_data.items():
            print(
                f"  {name:<15} {data['BUY']:>5} {data['SELL']:>5} "
                f"{data['HOLD']:>5} {data['avg_conf']:>10.2f}"
            )

    # Notable Decisions (top 5 by confidence, excluding PARSE_ERROR)
    valid = [
        (aid, d) for aid, d in agent_decisions
        if d.signal != SignalType.PARSE_ERROR
    ]
    top5 = sorted(valid, key=lambda x: x[1].confidence, reverse=True)[:5]
    print(f"\n  Notable Decisions (Top 5 by Confidence)")
    print(f"  {'-'*55}")
    for agent_id, decision in top5:
        snippet = _sanitize_rationale(decision.rationale, max_len=80)
        print(
            f"  {agent_id:<20} {decision.signal.value.upper():<5} "
            f"{decision.confidence:.2f}  {snippet}"
        )
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Shift analysis (Phase 7)
# ---------------------------------------------------------------------------


def _print_shift_analysis(
    shift: ShiftMetrics,
    prev_round: int,
    curr_round: int,
) -> None:
    """Print signal transition counts and per-bracket confidence drift.

    Per UI-SPEC: transition pairs in two columns, bracket delta with sign prefix.
    When no agents shifted, prints a single-line message instead of empty table.

    ShiftMetrics uses tuple fields for immutability. Convert to dict for lookup.
    """
    transitions = dict(shift.signal_transitions)

    print(f"  Signal Transitions (Round {prev_round} -> Round {curr_round})")
    print(f"  {'-'*40}")

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
        print(f"  Total agents shifted: {shift.agents_shifted}/100")

    bracket_deltas = dict(shift.bracket_confidence_delta)
    if bracket_deltas:
        print(f"\n  Confidence Drift by Bracket")
        print(f"  {'-'*40}")
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
) -> None:
    """Print the final simulation summary with convergence indicator.

    Convergence logic (addresses Codex review equal-flips edge case):
    - Yes: Round 2->3 flips < Round 1->2 flips ("flips decreased between rounds")
    - No:  Round 2->3 flips > Round 1->2 flips ("flips increased between rounds")
    - No:  Round 2->3 flips == Round 1->2 flips ("flips unchanged between rounds")
    """
    r2_flips = result.round2_shifts.total_flips
    r3_flips = result.round3_shifts.total_flips
    total_flips = r2_flips + r3_flips

    if r3_flips < r2_flips:
        convergence_label = "Yes"
        convergence_detail = "flips decreased between rounds"
    elif r3_flips > r2_flips:
        convergence_label = "No"
        convergence_detail = "flips increased between rounds"
    else:
        convergence_label = "No"
        convergence_detail = "flips unchanged between rounds"

    print(f"{'='*60}")
    print("  Simulation Complete")
    print(f"{'='*60}")
    print(f"  Cycle ID:       {result.cycle_id}")
    print(f"  Total Rounds:   3")
    print(f"  Signal Flips:   {r2_flips} (R1->R2) + {r3_flips} (R2->R3) = {total_flips} total")
    print(f"  Convergence:    {convergence_label} ({convergence_detail})")

    # Final Consensus Distribution (Round 3 decisions)
    print(f"\n  Final Consensus Distribution")
    print(f"  {'-'*40}")
    # Use promoted BracketSummary from SimulationResult (D-08)
    if result.round3_summaries:
        _print_bracket_table_from_summaries(result.round3_summaries)
    else:
        # Fallback for backward compatibility (pre-Phase 8 results or empty summaries)
        decisions_list = list(result.round3_decisions)
        bracket_data = _aggregate_brackets(decisions_list, personas, brackets)
        print(f"  {'Bracket':<15} {'BUY':>5} {'SELL':>5} {'HOLD':>5} {'Avg Conf':>10}")
        print(f"  {'-'*15} {'-'*5} {'-'*5} {'-'*5} {'-'*10}")
        for name, data in bracket_data.items():
            print(
                f"  {name:<15} {data['BUY']:>5} {data['SELL']:>5} "
                f"{data['HOLD']:>5} {data['avg_conf']:>10.2f}"
            )
    print(f"{'='*60}")


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
            )

    return handler


# ---------------------------------------------------------------------------
# Async pipeline (owns schema, full 3-round simulation, final summary, cleanup)
# ---------------------------------------------------------------------------


async def _run_pipeline(
    rumor: str,
    settings: AppSettings,
    app: AppState,
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
) -> None:
    """Async pipeline: schema -> full 3-round simulation -> final summary.

    Per D-17: _run_pipeline calls run_simulation() instead of run_round1().
    Per D-14: reports print DURING simulation via on_round_complete callback.
    Addresses Gemini/Codex review: truly progressive output, not buffered.
    """
    from alphaswarm.simulation import run_simulation

    assert app.graph_manager is not None
    assert app.ollama_client is not None
    assert app.model_manager is not None

    try:
        await app.graph_manager.ensure_schema()

        print("Starting 3-round simulation...")

        # Create callback for progressive per-round output
        handler = _make_round_complete_handler(personas, brackets)

        result = await run_simulation(
            rumor=rumor,
            settings=settings,
            ollama_client=app.ollama_client,
            model_manager=app.model_manager,
            graph_manager=app.graph_manager,
            governor=app.governor,
            personas=personas,
            brackets=brackets,
            on_round_complete=handler,
            state_store=app.state_store,
        )

        # Final summary (only this prints AFTER run_simulation returns)
        _print_simulation_summary(result, personas, brackets)

    finally:
        await app.graph_manager.close()


# ---------------------------------------------------------------------------
# Synchronous CLI handler (creates AppState BEFORE event loop)
# ---------------------------------------------------------------------------


def _handle_run(rumor: str) -> None:
    """Synchronous CLI handler -- creates AppState BEFORE event loop starts.

    Addresses review concern #2 (Codex HIGH): create_app_state() calls
    run_until_complete() for Neo4j connectivity check, which is UNSAFE
    inside a running event loop. This handler creates AppState synchronously
    BEFORE asyncio.run() starts the loop.
    """
    from alphaswarm.app import create_app_state

    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)

    assert app.ollama_client is not None
    assert app.model_manager is not None
    assert app.graph_manager is not None

    # NOW start the event loop with the async pipeline
    asyncio.run(_run_pipeline(rumor, settings, app, personas, brackets))


# ---------------------------------------------------------------------------
# TUI handler (creates AppState BEFORE Textual event loop)
# ---------------------------------------------------------------------------


def _handle_tui(rumor: str) -> None:
    """Synchronous handler: create AppState BEFORE Textual event loop.

    Per D-01: TUI-owned event loop. AppState (including Neo4j driver
    verification via run_until_complete) must be created synchronously
    BEFORE App.run() starts the Textual event loop.

    Mirrors _handle_run pattern for startup safety.
    """
    from alphaswarm.app import create_app_state
    from alphaswarm.tui import AlphaSwarmApp

    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)

    # MUST happen BEFORE App.run() -- create_app_state uses run_until_complete
    # for Neo4j connectivity check, which crashes inside a running event loop
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)

    tui_app = AlphaSwarmApp(
        rumor=rumor,
        app_state=app_state,
        personas=personas,
        brackets=brackets,
        settings=settings,
    )
    tui_app.run()


# ---------------------------------------------------------------------------
# Inject handler (existing, unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point with argparse subcommand routing."""
    parser = argparse.ArgumentParser(
        prog="alphaswarm",
        description="AlphaSwarm: Multi-agent financial simulation engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    inject_parser = subparsers.add_parser("inject", help="Inject a seed rumor")
    inject_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")

    run_parser = subparsers.add_parser("run", help="Run full 3-round simulation")
    run_parser.add_argument("rumor", type=str, help="Natural-language seed rumor text")

    tui_parser = subparsers.add_parser("tui", help="Launch TUI dashboard with live simulation")
    tui_parser.add_argument(
        "rumor", type=str, nargs="?", default="",
        help="Natural-language seed rumor text (optional — can be entered in the TUI)",
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
            _handle_run(args.rumor)
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("run_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "tui":
        try:
            _handle_tui(args.rumor)
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            logger.error("tui_failed", error=str(e))
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        _print_banner()
