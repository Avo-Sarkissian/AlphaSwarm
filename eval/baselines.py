#!/usr/bin/env python3
"""Worker-only baselines and the memorization probe (docs/methodology.md §5, §8).

    uv run python eval/baselines.py single          # k=5 per unit: named seeds 1-3, anon seed 1
    uv run python eval/baselines.py sc [--k 200]    # compute-matched self-consistency, named seeds 1-3
    uv run python eval/baselines.py probe           # one recall probe per event (named, no context)

Records append to eval/results/{baselines,probes}.jsonl after each finished unit, so a
rerun skips finished units. Owner's shell only: these are real model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.batch_dispatcher import HARD_STOP_ERRORS
from alphaswarm.errors import StructuredOutputError
from alphaswarm.evaluation import (
    DEFAULT_SC_K,
    EVAL_SEEDS,
    SINGLE_K,
    BaselineKind,
    BaselineRecord,
    EvalEvent,
    EvalPaths,
    ProbeAnswer,
    ProbeRecord,
    Variant,
    append_jsonl,
    headcount_score,
    mean_bracket_temperature,
    read_jsonl,
    read_jsonl_if_exists,
    sim_seed_for,
)
from alphaswarm.inference.structured import chat_structured
from alphaswarm.ingestion.fixture import load_context_fixture
from alphaswarm.manifest import derive_call_seed
from alphaswarm.personas import (
    DEFAULT_BRACKETS,
    generate_personas,
    load_bracket_configs,
    persona_to_worker_config,
)
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.simulation import fixture_market_context
from alphaswarm.types import AgentDecision, SignalType, WorkerPersonaConfig
from alphaswarm.worker import agent_worker

if TYPE_CHECKING:
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.inference.types import InferenceMessage

EVAL_DIR: Final = Path(__file__).resolve().parent
PATHS: Final = EvalPaths(EVAL_DIR)
BASELINE_AGENT_ID: Final = "baseline_analyst_01"
BASELINE_TEMPERATURE: Final = mean_bracket_temperature(DEFAULT_BRACKETS)
BASELINE_ANALYST_PROMPT: Final = (
    "You are an experienced equity analyst. Read the market report in the user message "
    "and decide how to position in the primary listed company it concerns over the next "
    "trading day: buy, sell or hold. Judge the report on its merits, give your confidence "
    "and a short rationale."
)
PROBE_SYSTEM_PROMPT: Final = (
    "You are a market historian. Answer only from what you specifically remember about "
    "this event. Do not guess and do not reason from general principles: if you do not "
    "specifically remember the stock's reaction, say so. Respond with JSON: "
    '{"recalled": bool, "direction": "up" | "down" | "flat" | "unknown", "rationale": str}'
)

log = structlog.get_logger(component="eval")

BlockFor = Callable[[EvalEvent, Variant], str | None]


def baseline_worker_config(template: WorkerPersonaConfig) -> WorkerPersonaConfig:
    """A persona-free analyst on the worker model, at the swarm's mean temperature."""
    config = template.copy()
    config["agent_id"] = BASELINE_AGENT_ID
    config["bracket"] = "baseline"
    config["influence_weight"] = 0.0
    config["temperature"] = BASELINE_TEMPERATURE
    config["system_prompt"] = f"{BASELINE_ANALYST_PROMPT}\n\n{JSON_OUTPUT_INSTRUCTIONS}"
    return config


def default_worker_config() -> WorkerPersonaConfig:
    return baseline_worker_config(persona_to_worker_config(generate_personas(load_bracket_configs())[0]))


def call_seeds(kind: BaselineKind, seed: int, k: int) -> list[int]:
    """Provider seeds for the k samples of one unit (docs/DECISIONS.md#adr-run-manifest)."""
    base = sim_seed_for(seed)
    return [derive_call_seed(base, f"baseline_{kind}", index) for index in range(1, k + 1)]


def probe_messages(event: EvalEvent) -> list[InferenceMessage]:
    day = event.timestamp.date().isoformat()
    question = (
        f"On {day} this was reported: {event.rumor}\n\n"
        f"Do you specifically remember how {event.primary_ticker} stock moved over the "
        "following five trading days relative to the overall market? If you do not "
        "specifically remember, answer recalled=false and direction=unknown."
    )
    return [
        {"role": "system", "content": PROBE_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def fixture_block(event: EvalEvent, variant: Variant) -> str | None:
    """The exact market block the swarm saw for this event and variant."""
    packet = load_context_fixture(PATHS.fixture(event.event_id, variant), not_after=event.timestamp)
    return fixture_market_context(packet)


async def sample_decisions(
    provider: InferenceProvider,
    controller: ConcurrencyController,
    config: WorkerPersonaConfig,
    *,
    rumor: str,
    market_context: str | None,
    seeds: Sequence[int],
) -> list[AgentDecision]:
    """One decision per seed through agent_worker; failures become PARSE_ERROR, hard stops raise."""

    async def one(seed: int) -> AgentDecision:
        try:
            async with agent_worker(config, controller, provider) as worker:
                return await worker.infer(rumor, market_context=market_context, seed=seed)
        except HARD_STOP_ERRORS:
            raise
        except Exception:
            log.warning("baseline_call_failed", seed=seed, exc_info=True)
            return AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(seed)) for seed in seeds]
    except* HARD_STOP_ERRORS as eg:
        raise eg.exceptions[0] from eg
    return [task.result() for task in tasks]


async def probe_event(
    provider: InferenceProvider,
    controller: ConcurrencyController,
    config: WorkerPersonaConfig,
    event: EvalEvent,
) -> ProbeRecord:
    """Ask the worker whether it remembers the event's outcome (no market context)."""
    async with agent_worker(config, controller, provider):
        try:
            result = await chat_structured(provider, probe_messages(event), ProbeAnswer, retries=1, temperature=0.0)
            answer, failed = result.value, False
        except StructuredOutputError:
            answer, failed = ProbeAnswer(recalled=False, direction="unknown"), True
    return ProbeRecord(
        event_id=event.event_id,
        recalled=answer.recalled,
        direction=answer.direction,
        parse_failed=failed,
        model=provider.model,
        created_at=datetime.now(UTC),
    )


@dataclass(frozen=True)
class Unit:
    event: EvalEvent
    variant: Variant
    seed: int


def baseline_units(kind: BaselineKind, events: Sequence[EvalEvent]) -> list[Unit]:
    """single_k5: named seeds 1-3 then anon seed 1; self_consistency: named seeds 1-3."""
    named = [Unit(event, "named", seed) for event in events for seed in EVAL_SEEDS]
    if kind == "single_k5":
        return named + [Unit(event, "anon", 1) for event in events]
    return named


def pending_units(units: Sequence[Unit], existing: Sequence[BaselineRecord], kind: BaselineKind) -> list[Unit]:
    done = {(r.event_id, r.variant, r.seed) for r in existing if r.kind == kind}
    return [u for u in units if (u.event.event_id, u.variant, u.seed) not in done]


async def run_baselines(
    kind: BaselineKind,
    units: Sequence[Unit],
    *,
    provider: InferenceProvider,
    controller: ConcurrencyController,
    config: WorkerPersonaConfig,
    k: int,
    block_for: BlockFor,
    paths: EvalPaths,
) -> int:
    """Sample every unit and append its record as soon as it finishes."""
    written = 0
    for unit in units:
        block = await asyncio.to_thread(block_for, unit.event, unit.variant)
        decisions = await sample_decisions(
            provider,
            controller,
            config,
            rumor=unit.event.rumor_for(unit.variant),
            market_context=block,
            seeds=call_seeds(kind, unit.seed, k),
        )
        score, n_valid = headcount_score(decisions)
        record = BaselineRecord(
            event_id=unit.event.event_id,
            variant=unit.variant,
            kind=kind,
            seed=unit.seed,
            k=k,
            n_valid=n_valid,
            score=score,
            model=provider.model,
            created_at=datetime.now(UTC),
        )
        await asyncio.to_thread(append_jsonl, paths.baselines, record)
        log.info(
            "baseline_unit_finished",
            kind=kind,
            event_id=unit.event.event_id,
            variant=unit.variant,
            seed=unit.seed,
            n_valid=n_valid,
        )
        written += 1
    return written


async def run_probes(
    events: Sequence[EvalEvent],
    *,
    provider: InferenceProvider,
    controller: ConcurrencyController,
    config: WorkerPersonaConfig,
    paths: EvalPaths,
    existing: Sequence[ProbeRecord],
) -> int:
    done = {record.event_id for record in existing}
    written = 0
    for event in events:
        if event.event_id in done:
            continue
        record = await probe_event(provider, controller, config, event)
        await asyncio.to_thread(append_jsonl, paths.probes, record)
        log.info("probe_finished", event_id=event.event_id, recalled=record.recalled)
        written += 1
    return written


async def _main_async(args: argparse.Namespace) -> int:
    from alphaswarm.inference.types import ProviderRole
    from alphaswarm.services.runtime import open_runtime
    from alphaswarm.settings import AppSettings

    events = await asyncio.to_thread(read_jsonl, PATHS.events, EvalEvent)
    wanted = {e for e in args.events.split(",") if e}
    if wanted:
        events = [e for e in events if e.event_id in wanted]
    async with open_runtime(AppSettings(), with_neo4j=False, apply_schema=False) as runtime:
        provider = await runtime.inference.open_role(ProviderRole.WORKER, "simulation")
        controller = await runtime.inference.build_controller(runtime.app_state.state_store)
        config = default_worker_config()
        await provider.prepare()
        await controller.start_monitoring()
        try:
            if args.command == "probe":
                probes = await asyncio.to_thread(read_jsonl_if_exists, PATHS.probes, ProbeRecord)
                written = await run_probes(
                    events,
                    provider=provider,
                    controller=controller,
                    config=config,
                    paths=PATHS,
                    existing=probes,
                )
            else:
                kind: BaselineKind = "single_k5" if args.command == "single" else "self_consistency"
                k = SINGLE_K if kind == "single_k5" else args.k
                records = await asyncio.to_thread(read_jsonl_if_exists, PATHS.baselines, BaselineRecord)
                units = pending_units(baseline_units(kind, events), records, kind)
                written = await run_baselines(
                    kind,
                    units,
                    provider=provider,
                    controller=controller,
                    config=config,
                    k=k,
                    block_for=fixture_block,
                    paths=PATHS,
                )
        finally:
            await controller.stop_monitoring()
            await provider.teardown()
            await provider.aclose()
    print(f"{args.command}: {written} new records")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="baselines", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("single", "single worker call, k=5"),
        ("sc", "compute-matched self-consistency"),
        ("probe", "memorization probe"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--events", default="", help="comma-separated event ids")
        if name == "sc":
            command.add_argument("--k", type=int, default=DEFAULT_SC_K)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted; finished units are saved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
