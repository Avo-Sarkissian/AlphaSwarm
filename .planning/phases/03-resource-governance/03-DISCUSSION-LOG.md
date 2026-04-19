# Phase 3: Resource Governance - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-24
**Phase:** 03-resource-governance
**Areas discussed:** Recovery strategy, Failure scope, Crisis policy, Observability

---

## Recovery Strategy

### Q1: Slot restoration after Green recovery

| Option | Description | Selected |
|--------|-------------|----------|
| Gradual ramp | Restore 2 slots every check_interval (2s) until baseline. Prevents thundering herd. | ✓ |
| Instant snap-back | Immediately restore to baseline (8). Fastest but risks re-triggering. | |
| Cooldown + snap-back | Wait fixed cooldown (10s sustained Green), then snap back. Conservative. | |

**User's choice:** Gradual ramp
**Notes:** None

### Q2: Scale above baseline

| Option | Description | Selected |
|--------|-------------|----------|
| Scale up when safe | If memory <60% for sustained checks, add slots above baseline up to max (16). | ✓ |
| Baseline is ceiling | Never exceed baseline (8). Simpler, more predictable. | |

**User's choice:** Scale up when safe
**Notes:** None

### Q3: Sustained Green checks before scale-up

| Option | Description | Selected |
|--------|-------------|----------|
| 3 consecutive Green checks | ~6s at 2s interval before adding above-baseline slots. Prevents premature scale-up. | ✓ |
| Immediate on headroom | Add slots as soon as memory <60%. Faster but more oscillation. | |
| You decide | Claude picks hysteresis threshold. | |

**User's choice:** 3 consecutive Green checks
**Notes:** None

### Q4: Post-crisis recovery target

| Option | Description | Selected |
|--------|-------------|----------|
| Reset to baseline | Always ramp back to baseline (8) first, then normal scale-up logic. | ✓ |
| Resume pre-incident level | Remember and ramp back to pre-incident slot count. | |

**User's choice:** Reset to baseline
**Notes:** None

---

## Failure Scope

### Q1: Batch definition for 20% failure threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Per-wave | Each dispatch wave (8-16 agents) is one batch. Most responsive. | ✓ |
| Rolling window | Track last N calls as sliding window. Smoother but slower. | |
| Per-round | All 100 agents. Very coarse. | |

**User's choice:** Per-wave
**Notes:** None

### Q2: Shrink magnitude per trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Halve current slots | Cut in half (min 1). Aggressive. | |
| Subtract 2 slots | Reduce by 2 per trigger (min 1). Gradual. | ✓ |
| Drop to 1 immediately | Emergency single-thread. Safest but slowest. | |

**User's choice:** Subtract 2 slots
**Notes:** None

### Q3: Batch-level retry

| Option | Description | Selected |
|--------|-------------|----------|
| No batch retry | OllamaClient 3x backoff sufficient. Failed agents get PARSE_ERROR. | ✓ |
| One batch-level retry | Re-dispatch failed agents once at reduced concurrency. | |
| You decide | Claude picks based on TaskGroup pattern fit. | |

**User's choice:** No batch retry
**Notes:** None

---

## Crisis Policy

### Q1: Sustained crisis behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Timeout + abort | After N minutes of sustained crisis with no progress, abort with clear error. | ✓ |
| Wait indefinitely | Keep trying at 1 slot. Operator can Ctrl+C. | |
| Checkpoint + suspend | Persist completed decisions, suspend, resume later. | |

**User's choice:** Timeout + abort
**Notes:** None

### Q2: Crisis timeout duration

| Option | Description | Selected |
|--------|-------------|----------|
| 5 minutes | Balanced patience vs waste. | ✓ |
| 2 minutes | Aggressive, may abort during transient spikes. | |
| You decide | Claude picks based on empirical patterns. | |

**User's choice:** 5 minutes
**Notes:** None

---

## Observability

### Q1: State transition surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| structlog + StateStore | Log + write metrics to SharedStateStore for future TUI. No TUI code in Phase 3. | ✓ |
| structlog only | Log only, defer all TUI integration to Phase 10. | |
| You decide | Claude decides observability surface area. | |

**User's choice:** structlog + StateStore
**Notes:** None

### Q2: Log levels

| Option | Description | Selected |
|--------|-------------|----------|
| INFO scale, WARNING crisis | Routine at INFO, throttle/pause at WARNING, abort at ERROR. | ✓ |
| All at INFO | Everything at INFO. Simpler but noisier. | |
| You decide | Claude picks log levels. | |

**User's choice:** INFO scale, WARNING crisis
**Notes:** None

### Q3: StateStore emit frequency

| Option | Description | Selected |
|--------|-------------|----------|
| On change only | Emit when slot count, pressure level, or state changes. Less noise. | ✓ |
| Every check interval | Emit every 2s regardless. Live updating but more churn. | |
| You decide | Claude decides. | |

**User's choice:** On change only
**Notes:** None

---

## Claude's Discretion

- Semaphore replacement strategy (BoundedSemaphore → resizable token-pool)
- memory_pressure subprocess parsing implementation
- StateStore metric key names and data shape
- Test fixture design for simulating memory pressure
- File organization (single governor.py vs split modules)

## Deferred Ideas

None — discussion stayed within phase scope
