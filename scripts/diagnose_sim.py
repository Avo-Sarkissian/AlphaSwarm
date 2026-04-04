#!/usr/bin/env python3
"""Diagnostic wrapper for AlphaSwarm simulation.

Runs the simulation headless (no TUI) with a background monitor that prints
timestamped status lines every 2 seconds. Shows exactly where the simulation
stalls so we can identify the blocking point.

Usage:
    uv run python scripts/diagnose_sim.py "Your seed rumor here"
    uv run python scripts/diagnose_sim.py  # uses default rumor
"""

from __future__ import annotations

import asyncio
import functools
import sys
import time
from datetime import datetime
from typing import Any

import psutil

# ---------------------------------------------------------------------------
# Probe infrastructure
# ---------------------------------------------------------------------------

_SIM_START = time.monotonic()
_CURRENT_STEP = "initializing"
_STEP_ENTERED = time.monotonic()
_STEP_COUNTER = 0
_AGENT_PROGRESS = ""  # e.g. "42/100"


def _ts() -> str:
    """Wall clock + elapsed since sim start."""
    elapsed = time.monotonic() - _SIM_START
    return f"[{datetime.now().strftime('%H:%M:%S')} +{elapsed:6.1f}s]"


def step(name: str) -> None:
    """Mark the simulation entering a new step."""
    global _CURRENT_STEP, _STEP_ENTERED, _STEP_COUNTER
    prev = _CURRENT_STEP
    prev_dur = time.monotonic() - _STEP_ENTERED
    _CURRENT_STEP = name
    _STEP_ENTERED = time.monotonic()
    _STEP_COUNTER += 1
    print(f"{_ts()} STEP {_STEP_COUNTER:>2}: {name}  (prev: {prev} took {prev_dur:.1f}s)")
    sys.stdout.flush()


def progress(current: int, total: int) -> None:
    """Update agent progress counter."""
    global _AGENT_PROGRESS
    _AGENT_PROGRESS = f"{current}/{total}"


# ---------------------------------------------------------------------------
# Background monitor coroutine
# ---------------------------------------------------------------------------

async def _monitor_loop(
    governor: Any,
    ollama_client: Any,
    interval: float = 3.0,
) -> None:
    """Print status line every `interval` seconds until cancelled."""
    from alphaswarm.governor import GovernorState

    while True:
        try:
            await asyncio.sleep(interval)

            # Memory
            mem = psutil.virtual_memory()
            mem_pct = mem.percent

            # macOS sysctl pressure
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sysctl", "-n", "kern.memorystatus_vm_pressure_level",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                pressure_val = int(stdout.decode().strip())
                pressure_map = {1: "GREEN", 2: "YELLOW", 4: "RED"}
                pressure = pressure_map.get(pressure_val, f"UNKNOWN({pressure_val})")
            except Exception:
                pressure = "N/A"

            # Governor state
            gov_state = governor.state.value
            gov_limit = governor.current_limit
            gov_active = governor.active_count
            gov_paused = governor.is_paused
            monitor_alive = "ALIVE" if (
                governor._monitor_task is not None
                and not governor._monitor_task.done()
            ) else "DEAD"
            resume_set = governor._resume_event.is_set()

            # Ollama model status
            try:
                ps = await ollama_client.raw_client.ps()
                models = [f"{m.model}({m.size // (1024**3)}GB)" for m in ps.models]
                model_str = ", ".join(models) if models else "NONE LOADED"
            except Exception as e:
                model_str = f"ERROR({e})"

            # Stuck detection
            step_dur = time.monotonic() - _STEP_ENTERED
            stuck_flag = " *** STUCK? ***" if step_dur > 120 else (
                " (slow)" if step_dur > 60 else ""
            )

            # Asyncio tasks
            all_tasks = asyncio.all_tasks()
            task_count = len(all_tasks)
            waiting_tasks = sum(1 for t in all_tasks if not t.done())

            print(
                f"{_ts()} STATUS | "
                f"step={_CURRENT_STEP} ({step_dur:.0f}s) | "
                f"agents={_AGENT_PROGRESS} | "
                f"gov={gov_state} slots={gov_active}/{gov_limit} "
                f"monitor={monitor_alive} resume={'SET' if resume_set else 'CLEARED'} | "
                f"mem={mem_pct:.0f}% pressure={pressure} | "
                f"ollama=[{model_str}] | "
                f"tasks={waiting_tasks}/{task_count}"
                f"{stuck_flag}"
            )
            sys.stdout.flush()

        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"{_ts()} MONITOR ERROR: {e}")


# ---------------------------------------------------------------------------
# Patched simulation with probes
# ---------------------------------------------------------------------------

async def run_diagnosed_simulation(rumor: str) -> None:
    """Run simulation with diagnostic probes injected at every key point."""
    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs

    step("loading config & personas")
    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)

    step("creating app state")
    app = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    assert app.ollama_client is not None
    assert app.model_manager is not None
    assert app.graph_manager is not None

    governor = app.governor
    ollama_client = app.ollama_client

    # Start background monitor
    monitor_task = asyncio.create_task(
        _monitor_loop(governor, ollama_client, interval=3.0)
    )

    try:
        step("ensure_schema")
        await app.graph_manager.ensure_schema()

        # Monkey-patch key functions with timing probes
        _patch_simulation_probes(app, settings, personas, brackets)

        step("run_simulation START")
        from alphaswarm.simulation import run_simulation

        result = await run_simulation(
            rumor=rumor,
            settings=settings,
            ollama_client=app.ollama_client,
            model_manager=app.model_manager,
            graph_manager=app.graph_manager,
            governor=governor,
            personas=list(personas),
            brackets=list(brackets),
            state_store=app.state_store,
        )

        step("SIMULATION COMPLETE")
        sigs = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for _, dec in result.round1_decisions:
            if dec.signal.value in sigs:
                sigs[dec.signal.value] += 1
        print(f"{_ts()} RESULT: {sigs}")

    except Exception as e:
        print(f"\n{_ts()} *** SIMULATION FAILED: {type(e).__name__}: {e} ***")
        import traceback
        traceback.print_exc()
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # Cleanup
        if app.graph_manager is not None:
            await app.graph_manager.close()


def _patch_simulation_probes(app: Any, settings: Any, personas: Any, brackets: Any) -> None:
    """Monkey-patch simulation internals with step() probes.

    Wraps key functions so we see exactly which step the simulation is on.
    """
    import alphaswarm.simulation as sim
    import alphaswarm.ollama_models as models
    import alphaswarm.batch_dispatcher as batch
    import alphaswarm.graph as graph

    # --- Patch model_manager ---
    orig_load = app.model_manager.load_model
    orig_unload = app.model_manager.unload_model
    orig_clean = app.model_manager.ensure_clean_state

    @functools.wraps(orig_load)
    async def patched_load(model: str) -> None:
        step(f"load_model({model})")
        await orig_load(model)
        step(f"load_model({model}) DONE")

    @functools.wraps(orig_unload)
    async def patched_unload(model: str) -> None:
        step(f"unload_model({model})")
        await orig_unload(model)

    @functools.wraps(orig_clean)
    async def patched_clean() -> None:
        step("ensure_clean_state")
        await orig_clean()

    app.model_manager.load_model = patched_load
    app.model_manager.unload_model = patched_unload
    app.model_manager.ensure_clean_state = patched_clean

    # --- Patch governor ---
    orig_start_mon = app.governor.start_monitoring
    orig_stop_mon = app.governor.stop_monitoring

    @functools.wraps(orig_start_mon)
    async def patched_start_mon() -> None:
        step("governor.start_monitoring")
        await orig_start_mon()

    @functools.wraps(orig_stop_mon)
    async def patched_stop_mon() -> None:
        step("governor.stop_monitoring")
        await orig_stop_mon()

    app.governor.start_monitoring = patched_start_mon
    app.governor.stop_monitoring = patched_stop_mon

    # --- Patch dispatch_wave with per-agent progress ---
    # simulation.py uses `from batch_dispatcher import dispatch_wave` so we
    # must patch the name on the simulation MODULE, not on batch_dispatcher.
    orig_dispatch = sim.dispatch_wave

    @functools.wraps(orig_dispatch)
    async def patched_dispatch(*args: Any, **kwargs: Any) -> Any:
        personas_arg = args[0] if args else kwargs.get("personas", [])
        n = len(personas_arg)
        step(f"dispatch_wave ({n} agents)")
        progress(0, n)

        # Patch _safe_agent_inference to count completions
        orig_safe = batch._safe_agent_inference
        _completed = {"count": 0}

        @functools.wraps(orig_safe)
        async def counting_inference(*a: Any, **kw: Any) -> Any:
            result = await orig_safe(*a, **kw)
            _completed["count"] += 1
            progress(_completed["count"], n)
            return result

        batch._safe_agent_inference = counting_inference
        try:
            result = await orig_dispatch(*args, **kwargs)
        finally:
            batch._safe_agent_inference = orig_safe

        step(f"dispatch_wave DONE ({n} agents)")
        return result

    sim.dispatch_wave = patched_dispatch

    # --- Patch graph read_ranked_posts to show progress ---
    orig_read_ranked = app.graph_manager.read_ranked_posts
    _read_batch = {"n": 0, "batch_start": 0}

    @functools.wraps(orig_read_ranked)
    async def patched_read_ranked(*args: Any, **kwargs: Any) -> Any:
        _read_batch["n"] += 1
        batch_n = _read_batch["n"] - _read_batch["batch_start"]
        if batch_n == 1:
            step("read_ranked_posts (sequential Neo4j queries)")
        t0 = time.monotonic()
        result = await orig_read_ranked(*args, **kwargs)
        dur = time.monotonic() - t0
        if batch_n % 25 == 0 or dur > 2.0:
            print(f"{_ts()}   ... read_ranked_posts {batch_n}/~100 (this={dur:.2f}s)")
            sys.stdout.flush()
        return result

    app.graph_manager.read_ranked_posts = patched_read_ranked

    # Reset counter when new dispatch starts (between Round 2 and Round 3 reads)
    _orig_set_round = app.state_store.set_round

    @functools.wraps(_orig_set_round)
    async def patched_set_round(round_num: int) -> None:
        _read_batch["batch_start"] = _read_batch["n"]  # reset counter for new round
        step(f"set_round({round_num})")
        await _orig_set_round(round_num)

    app.state_store.set_round = patched_set_round

    # --- Patch write_read_post_edges ---
    orig_write_edges = app.graph_manager.write_read_post_edges

    @functools.wraps(orig_write_edges)
    async def patched_write_edges(*args: Any, **kwargs: Any) -> None:
        agent_ids = args[0] if args else kwargs.get("agent_ids", [])
        post_ids = args[1] if len(args) > 1 else kwargs.get("post_ids", [])
        n = len(agent_ids) * len(post_ids)
        step(f"write_read_post_edges ({n} edges)")
        await orig_write_edges(*args, **kwargs)
        step("write_read_post_edges DONE")

    app.graph_manager.write_read_post_edges = patched_write_edges

    # --- Patch inject_seed ---
    orig_inject = sim.inject_seed

    @functools.wraps(orig_inject)
    async def patched_inject(*args: Any, **kwargs: Any) -> Any:
        step("inject_seed (orchestrator model)")
        result = await orig_inject(*args, **kwargs)
        step("inject_seed DONE")
        return result

    sim.inject_seed = patched_inject

    # --- Patch run_round1 ---
    orig_round1 = sim.run_round1

    @functools.wraps(orig_round1)
    async def patched_round1(*args: Any, **kwargs: Any) -> Any:
        step("run_round1")
        result = await orig_round1(*args, **kwargs)
        step("run_round1 DONE")
        return result

    sim.run_round1 = patched_round1

    # --- Patch compute_influence_edges ---
    orig_compute = app.graph_manager.compute_influence_edges

    @functools.wraps(orig_compute)
    async def patched_compute(*args: Any, **kwargs: Any) -> Any:
        step("compute_influence_edges")
        result = await orig_compute(*args, **kwargs)
        step("compute_influence_edges DONE")
        return result

    app.graph_manager.compute_influence_edges = patched_compute


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    rumor = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "BREAKING: Apple to acquire OpenAI for $150B, sources say deal closes Q3 2026"
    )
    print(f"\n{'='*70}")
    print(f"  AlphaSwarm Diagnostic Run")
    print(f"  Rumor: {rumor[:60]}...")
    print(f"  Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    sys.stdout.flush()

    global _SIM_START
    _SIM_START = time.monotonic()

    asyncio.run(run_diagnosed_simulation(rumor))


if __name__ == "__main__":
    main()
