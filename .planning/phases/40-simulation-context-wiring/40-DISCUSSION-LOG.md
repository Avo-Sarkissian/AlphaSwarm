# Phase 40: Simulation Context Wiring - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 40-simulation-context-wiring
**Areas discussed:** Assembly ownership, Prompt injection mechanics, Provider wiring, Context content selection

---

## Assembly Ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Inside run_simulation | After inject_seed extracts entities, run_simulation calls providers and assembles packet internally | ✓ |
| External pre-assembly | SimulationManager/cli call inject_seed first externally, then assemble packet, pass to run_simulation with pre_injected | |
| Separate assembly step | Standalone assemble_context() function called by orchestrators | |

**User's choice:** Inside run_simulation — entity extraction and context assembly happen in one flow.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Skip silently | No providers = no context, proceed with rumor-only | |
| Log a warning, skip | Emit context_assembly_skipped log event before proceeding | ✓ |
| You decide | Claude picks | |

**User's choice:** Log a warning, skip — helps debug misconfigured deployments.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Include all, formatter skips failed | ContextPacket carries all slices; formatter omits fetch_failed entries | ✓ |
| Pre-filter fresh only | Filter before ContextPacket construction | |
| You decide | Claude picks | |

**User's choice:** Include all, formatter skips — consistent with Phase 38 D-19 never-raise design.

---

## Prompt Injection Mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| System message, mirrors peer_context | Add as system message before user message; dispatch_wave gains market_context param | ✓ |
| Appended to user_message | Format as block appended to rumor text; no new params needed | |
| You decide | Claude picks | |

**User's choice:** System message pattern — clean separation, mirrors existing peer_context plumbing.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — new market_context param flows through | dispatch_wave + agent_worker.infer both gain market_context: str \| None | ✓ |
| No — fold into user_message | Pre-format in run_round1, no signature changes downstream | |
| You decide | Claude picks | |

**User's choice:** New param flows through — consistent with peer_context precedent.

---

## Provider Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| app.state, constructed in lifespan | Providers constructed once in FastAPI lifespan, stored on app.state | ✓ |
| Per-simulation construction | Providers created fresh each simulation run | |
| You decide | Claude picks | |

**User's choice:** app.state lifespan — follows existing state object patterns.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Wire real providers in CLI | cli.py constructs providers inline, passes to run_simulation | ✓ |
| CLI uses None | Context is web-only; CLI skips providers | |
| CLI flag to opt in | --with-context flag for explicit opt-in | |

**User's choice:** Real providers in CLI — same grounded context experience on both paths.

---

## Context Content Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Same block for all 100 agents | One formatted block, passed identically via dispatch_wave | ✓ |
| Per-bracket filtering | Quants/Degens/Whales get different field subsets | |
| You decide | Claude picks | |

**User's choice:** Same block — simpler, avoids 100x formatting overhead.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Price + top headlines only | Skip fundamentals; ~200 tokens per agent | |
| Price + fundamentals + headlines | Full price, pe_ratio, eps, market_cap, headlines | ✓ |
| You decide | Claude picks | |

**User's choice:** Full price + fundamentals + headlines — richer signal for agents.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Top 3 headlines per entity | Conservative cap | |
| Top 5 headlines per entity | More coverage | ✓ |
| You decide | Claude picks | |

**User's choice:** Top 5 per entity.

---

## Claude's Discretion

- Exact string formatting of the market context block
- Whether fetch_batch receives all entities or only ticker-shaped ones
- app.state typed slots vs dynamic attribute pattern for providers
- SimulationManager constructor vs _run() time provider access

## Deferred Ideas

- Per-bracket context filtering — possible v7.0 quality improvement
- Context staleness TTL — deferred from Phase 38, still deferred
- RSS feed caching between simulation runs in same session — deferred
