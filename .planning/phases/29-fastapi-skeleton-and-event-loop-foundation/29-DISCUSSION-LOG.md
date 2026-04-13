# Phase 29: FastAPI Skeleton and Event Loop Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the rationale.

**Date:** 2026-04-12
**Phase:** 29-fastapi-skeleton-and-event-loop-foundation
**Mode:** discuss
**Areas discussed:** Web module layout, SimulationManager design, alphaswarm web CLI args

## Gray Areas Presented

| Area | Options | Selected |
|------|---------|----------|
| Web module layout | web/ package vs. single web.py | web/ package |
| SimulationManager design | Dedicated class vs. flag on AppState | Dedicated class (web/simulation_manager.py) |
| alphaswarm web CLI args | --host/--port only vs. add --reload | --host/--port only |

## Discussion Details

### Web Module Layout
- **Options presented:** `src/alphaswarm/web/` package with `app.py` + `routes/` sub-router pattern vs. single flat `web.py`
- **Decision:** `web/` package — sets the pattern for all 7 remaining v5.0 phases; sub-router per domain makes phase-by-phase endpoint addition clean
- **Rationale:** Each downstream phase (30-36) adds a route file without touching the factory

### SimulationManager Design
- **Options presented:** New `SimulationManager` class in `web/simulation_manager.py` with async lock + `is_running` guard vs. boolean flag added to existing `AppState`
- **Decision:** Dedicated `SimulationManager` class — keeps web-layer concurrency concern out of core `AppState`; Phase 32 REST endpoints call it directly
- **Rationale:** AppState is already shared across all subsystems; mixing web-layer guard state into it creates coupling

### alphaswarm web CLI Args
- **Options presented:** `--host/--port` only vs. also expose `--reload` for dev mode
- **Decision:** `--host/--port` only — `--reload` is an IDE/development concern, not a production CLI arg; matches localhost-only constraint
- **Rationale:** Keep CLI surface minimal for the skeleton phase

## Pre-Locked Decisions (not re-discussed)

From STATE.md accumulated context:
- Uvicorn must own the asyncio event loop — all objects created inside FastAPI lifespan
- StateStore.snapshot() → non-destructive; separate drain_rationales() called once per broadcast tick
- Post-simulation-only interview gating (Phase 35 concern, not Phase 29)
