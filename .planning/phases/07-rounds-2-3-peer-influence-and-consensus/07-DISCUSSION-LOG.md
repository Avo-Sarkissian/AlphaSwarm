# Phase 7: Rounds 2-3 Peer Influence and Consensus - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 07-rounds-2-3-peer-influence-and-consensus
**Areas discussed:** Peer context formatting, Round progression strategy, Opinion shift detection, CLI output evolution

---

## Peer Context Formatting

| Option | Description | Selected |
|--------|-------------|----------|
| Structured summary | Compact text block per peer: bracket, signal, confidence, 80-char rationale. ~250 tokens for 5 peers. | ✓ |
| Minimal table | Bracket + signal + confidence only, no rationale. ~75 tokens. | |
| Full JSON | Raw PeerDecision fields as JSON. ~500 tokens. | |

**User's choice:** Structured summary
**Notes:** Balances information density with token budget. Agents need rationale snippets to reason about WHY peers decided.

### Follow-up: Rationale Length

| Option | Description | Selected |
|--------|-------------|----------|
| 80 chars | Matches Phase 6 _sanitize_rationale() pattern | ✓ |
| 150 chars | More reasoning signal but eats into 4K context | |
| You decide | Claude picks based on token analysis | |

**User's choice:** 80 chars
**Notes:** Consistency with Phase 6 pattern.

---

## Round Progression Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Single run_simulation() | One top-level function, worker stays loaded for Rounds 2-3. State machine transitions. | ✓ |
| Separate run_round2/run_round3 | Each round its own function. More modular but 2x cold loads. | |
| Hybrid | run_simulation wraps run_roundN functions. | |

**User's choice:** Single run_simulation()
**Notes:** Worker stays loaded across rounds for performance. Clean state machine.

### Follow-up: Round 1 Reuse

| Option | Description | Selected |
|--------|-------------|----------|
| Call existing run_round1() | Preserves Phase 6 code, run_round1() still works standalone | ✓ |
| Inline Round 1 | Move logic into run_simulation(), deprecate run_round1() | |

**User's choice:** Call existing run_round1()
**Notes:** One extra worker reload cost for preserving modularity. run_round1() remains a standalone function.

---

## Opinion Shift Detection

| Option | Description | Selected |
|--------|-------------|----------|
| Signal flips + confidence delta | Count signal changes, compute avg confidence delta per bracket | ✓ |
| Full diff report per agent | Track every field change for all 100 agents. Comprehensive but verbose. | |
| Bracket-level only | Aggregate at bracket level. Clean but misses outlier behavior. | |

**User's choice:** Signal flips + confidence delta
**Notes:** Maps directly to success criterion #4. Signal change breakdown + per-bracket confidence drift.

---

## CLI Output Evolution

| Option | Description | Selected |
|--------|-------------|----------|
| Per-round bracket tables + final summary | Print bracket table after each round, shift analysis, final convergence summary | ✓ |
| Final summary only | One report after all 3 rounds. User waits with no feedback. | |
| Combined evolution table | Single table showing all 3 rounds side-by-side. Compact but complex. | |

**User's choice:** Per-round bracket tables + final summary
**Notes:** Progressive output during ~10 minute simulation. Reuses _print_round1_report() pattern.

---

## Claude's Discretion

- Internal helper function structure within run_simulation()
- Parallelization strategy for per-agent peer reads
- SimulationResult field naming beyond core round results
- Shift analysis output formatting details
- Handling of identical top-5 peers across agents (static ranking)
- Whether run_round1() standalone needs a separate CLI flag

## Deferred Ideas

None — discussion stayed within phase scope
