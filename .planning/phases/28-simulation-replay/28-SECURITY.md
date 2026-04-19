---
phase: 28
slug: simulation-replay
status: verified
threats_open: 0
asvs_level: 1
audited: 2026-04-12
---

# Security Review — Phase 28: Simulation Replay

## Threat Register

| ID | Severity | Category | Component | Disposition | Status |
|----|----------|----------|-----------|-------------|--------|
| T-01 | HIGH | Injection | `graph.py` — replay read methods | Parameterized `$cycle_id` in all 4 new Cypher queries; no f-string interpolation | CLOSED |
| T-02 | LOW | DoS | `graph.py` — `read_full_cycle_signals` | Acceptable risk — max 300 rows (100 agents × 3 rounds), cycle-scoped by composite index; no LIMIT needed | CLOSED |
| T-03 | LOW | DoS | `graph.py` — `read_completed_cycles` | `LIMIT $limit` hardcoded at 10; cannot return unbounded results | CLOSED |
| T-04 | MEDIUM | Injection | `cli.py` — `replay` subcommand | `cycle_id` passed as `$cycle_id` Neo4j parameter; validated at argparse level as string; inherits T-01 pattern | CLOSED |
| T-05 | MEDIUM | Race | `tui.py` — `_poll_snapshot` during replay entry | `_replay_store` set **before** any phase change (explicit `ORDERING` comment at line 1061); `_poll_snapshot` gates on `_replay_store is not None` | CLOSED |
| T-06 | LOW | Resource Leak | `tui.py` — replay timer | `action_exit_replay()` calls `_replay_timer.stop()` and sets `_replay_timer = None` at lines 1267-1269 | CLOSED |
| T-07 | HIGH | Data Integrity | `tui.py` — `StateStore` isolation | `StateStore` is never written during replay; `_poll_snapshot` branches exclusively on `_replay_store is not None` at line 1305 | CLOSED |
| T-08 | MEDIUM | Race | `tui.py` — `_load_replay_round_data` | Stale-round guard checks `round_num == self._replay_round` on both `await` points (lines 1116, 1139); stale data discarded | CLOSED |

## Evidence

All mitigations verified against codebase on 2026-04-12:

- **T-01/T-04:** `grep -n "\$cycle_id" src/alphaswarm/graph.py` — lines 1788, 1836, 1880, 1931, 1939 all use parameterized form. Zero f-string `cycle_id` interpolation in Cypher strings.
- **T-02:** `read_full_cycle_signals` scoped to single `cycle_id`; data model caps at 300 rows.
- **T-03:** `LIMIT $limit` with default 10 at `graph.py:1836`.
- **T-05:** `tui.py:1085` — `self._replay_store = ReplayStore(...)` precedes any phase mutation. Explicit `ORDERING` docstring documents invariant.
- **T-06:** `tui.py:1267-1269` — `_replay_timer.stop()` + `= None` in `action_exit_replay`.
- **T-07:** `grep "state_store\." tui.py` — no writes to `state_store` inside replay branches.
- **T-08:** `tui.py:1116,1139` — double guard pattern on both awaits in `_load_replay_round_data`.

## Accepted Risks

None.

## Audit Trail

### Security Audit 2026-04-12

| Metric | Count |
|--------|-------|
| Threats found | 8 |
| Closed | 8 |
| Open | 0 |

All mitigations confirmed present in code. No auditor spawn required (threats_open: 0 detected from PLAN.md dispositions + code verification).
