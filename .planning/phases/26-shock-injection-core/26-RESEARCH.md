# Phase 26: Shock Injection Core - Research

**Researched:** 2026-04-10
**Domain:** Inter-round pause/resume coordination, async queue-based TUI↔simulation bridge, Textual modal overlay pattern, Neo4j ShockEvent persistence
**Confidence:** HIGH

## Summary

Phase 26 adds the ability to inject a breaking event between simulation rounds. The mechanism decomposes into four small, orthogonal additions that all follow patterns already proven in the codebase:

1. **Governor pause gate:** two one-line methods (`suspend()` / `resume()`) that flip the existing `_resume_event` that `acquire()` already blocks on. No state-machine change, no monitoring-loop change.
2. **StateStore shock channel:** one `asyncio.Queue(maxsize=1)` and one `asyncio.Event`, mirroring the `_rationale_queue` pattern at `state.py:109` — StateStore is already the canonical simulation↔TUI bridge.
3. **TUI overlay:** one new `ShockInputScreen(Screen[str | None])` copy-paste template from `RumorInputScreen` at `tui.py:385-450`, pushed from `_poll_snapshot()` (same sync-timer-pushes-modal pattern as `action_open_interview` at `tui.py:779-787`).
4. **Neo4j persistence:** one new `write_shock_event()` using the existing session-per-method `execute_write` pattern at `graph.py:101-106`, one new `ShockEvent` node label plus a `(Cycle)-[:HAS_SHOCK]->(ShockEvent)` edge, one schema index added to `SCHEMA_STATEMENTS`.

Because CONTEXT.md has already locked every architectural decision (D-01 through D-17), this research is a verification + pitfall catalog, not an exploration. The primary risks are all in the governor pause mechanics (where five bugs were fixed in commits 9bd6dfa and 85cade8 7 days ago), and those risks are specifically what D-01..D-03 are designed to avoid.

**Primary recommendation:** Implement in dependency order — governor `suspend()`/`resume()` first (smallest, blocks all other tasks), then StateStore queue/event, then simulation.py inter-round wiring, then TUI overlay, then Neo4j persistence. Write a TUI integration test using `app.run_test(size=(...))` + `Pilot` (already proven in `tests/test_tui.py`) and a governor test that asserts `suspend()` does not trip `_monitor_loop` state transitions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Governor Suspend/Resume**
- **D-01:** Add `suspend()` and `resume()` methods to `ResourceGovernor` that only clear/set `_resume_event` — no state-machine transitions and no interaction with the monitoring loop. The monitoring loop continues running throughout the shock pause.
- **D-02:** `_resume_event.clear()` in `suspend()` blocks all new `acquire()` calls; `_resume_event.set()` in `resume()` unblocks them. This is the minimal intervention that prevents false THROTTLED/PAUSED states.
- **D-03:** Do NOT call `stop_monitoring()` / `start_monitoring()` between rounds for the shock pause — that pattern is too destructive (drains pool, resets state to RUNNING, risks immediate false THROTTLED on restart).

**Shock Queue Architecture**
- **D-04:** Add `asyncio.Queue(maxsize=1)` and `asyncio.Event` (shock window flag) to `StateStore` — consistent with the existing `_rationale_queue` pattern at `state.py:109`.
- **D-05:** `run_simulation()` suspends the governor at each inter-round gap, sets the shock-window event on StateStore (signaling TUI to show the overlay), then `await`s the queue. On receipt, resumes the governor and clears the shock-window flag.
- **D-06:** The TUI's shock overlay submits text by putting it onto the StateStore queue — same unidirectional StateStore-as-bridge pattern, no second inter-task channel.
- **D-07:** The shock window is optional per-round — if the user dismisses the overlay without submitting, simulation continues with no shock for that round (queue message = `None` or empty string).

**Agent Prompt Propagation**
- **D-08:** In `simulation.py`, after reading the shock from the queue, compute `effective_message = f"{rumor}\n\n[BREAKING] {shock_text}"` and pass it to `dispatch_wave(user_message=effective_message, ...)` for the shocked round.
- **D-09:** No changes to `AgentWorker`, `dispatch_wave`, or `_safe_agent_inference` — shock travels through the existing `user_message` parameter chain unchanged (`batch_dispatcher.py:67-68`, `worker.py:87-92`).
- **D-10:** If no shock was submitted (user dismissed), pass bare `rumor` as usual — zero behavioral change for unshocked rounds.

**Neo4j Persistence**
- **D-11:** Create a new `ShockEvent` node label with properties: `{shock_id, cycle_id, shock_text, injected_before_round, created_at}`.
- **D-12:** Relationship: `(c:Cycle)-[:HAS_SHOCK]->(se:ShockEvent)` — Cycle is the natural parent (already exists as simulation root node).
- **D-13:** Write uses the existing session-per-method pattern in `GraphStateManager` (`graph.py:101-106`). Called from `run_simulation()` after shock text received but before the shocked round's `dispatch_wave`.
- **D-14:** No `PRECEDES` edge to `Decision` nodes in this phase — that traversal is for Phase 27 analysis. Keep schema minimal for Phase 26.

**TUI Shock Input**
- **D-15:** Implement as a new `ShockInputScreen` overlay (pushed via `push_screen()`, same pattern as `InterviewScreen` at `tui.py:779-787`), not an inline docked widget.
- **D-16:** The `_poll_snapshot()` 200ms timer detects the shock-window event on StateStore and calls `self.push_screen(ShockInputScreen(...))`. On dismiss, the screen's return value (shock text or `None`) is put onto the StateStore queue.
- **D-17:** `ShockInputScreen` mirrors `RumorInputScreen` structure (`tui.py:385-450`): single `Input` widget, submit on Enter, dismiss with the text. Header label distinguishes it ("Inject Breaking Event").

### Claude's Discretion
- Exact `shock_id` generation strategy (UUID4 is fine)
- Whether to add a Neo4j index on `ShockEvent.cycle_id` (consistent with schema conventions but not strictly required for 1-2 shocks per cycle)
- Placeholder label text in `ShockInputScreen`
- Whether Round 1 can be shocked (likely not — shock only applies to Rounds 2 and 3 since there's no "previous round" to react against)

### Deferred Ideas (OUT OF SCOPE)
- `(ShockEvent)-[:PRECEDES]->(Decision)` relationship — useful for Phase 27 shock impact traversal but explicitly deferred from Phase 26 to keep the schema minimal
- Multi-shock support (more than one shock per cycle) — the node-per-shock schema supports this structurally, but the queue is maxsize=1 for Phase 26; multi-shock is a Phase 27+ concern
- Shocking Round 1 — likely not meaningful (no peer context to contrast against); Phase 27 analysis will confirm whether to enable it
</user_constraints>

<phase_requirements>
## Phase Requirements

SHOCK-01, SHOCK-02, SHOCK-03 are not yet defined in `.planning/REQUIREMENTS.md` — per CONTEXT.md `<canonical_refs>`, the phase execution should create these entries. Based on the phase Goal and Success Criteria in ROADMAP.md, the inferred requirement bodies are:

| ID | Description (inferred from Success Criteria) | Research Support |
|----|----------------------------------------------|------------------|
| SHOCK-01 | User can type a breaking event into a TUI input widget between rounds and submit it | D-04..D-07 StateStore queue + D-15..D-17 ShockInputScreen + verified Textual `push_screen(..., callback)` / `dismiss(value)` pattern and existing `RumorInputScreen` template at `tui.py:385-450` |
| SHOCK-02 | All 100 agents in the next round's batch receive the shock text in their prompt context and the governor does not enter false THROTTLED/PAUSED states during the shock pause | D-01..D-03 governor `suspend()`/`resume()` flipping `_resume_event` only + D-08..D-10 `dispatch_wave(user_message=effective_message, ...)` — verified `user_message` pass-through at `batch_dispatcher.py:67-68` and `worker.py:87-92` |
| SHOCK-03 | `ShockEvent` is persisted to Neo4j with `cycle_id` and `injected_before_round`, queryable after simulation ends | D-11..D-13 new `write_shock_event()` following the existing `execute_write` session-per-method pattern at `graph.py:101-106` and the `_batch_write_decisions_tx` transaction template at `graph.py:328-379` |

**Note to planner:** A task in Wave 0 (or Plan 01) should add the formal SHOCK-01/02/03 entries to `REQUIREMENTS.md` with the traceability table row pointing to Phase 26, per the existing convention in the Traceability table.
</phase_requirements>

## Project Constraints (from CLAUDE.md)

| Directive | How Phase 26 complies |
|-----------|------------------------|
| 100% async (`asyncio`), no blocking I/O on main loop | Governor `suspend()`/`resume()` are sync single-line `Event.clear()`/`.set()` calls (non-blocking). Queue operations are `await queue.put()` / `await queue.get()`. `_poll_snapshot()` remains sync and pushes the screen without awaiting. |
| Local first, Ollama only | Zero new external services. Shock text is a user-provided string, no extra inference. |
| Memory safety via `psutil` + governor throttle/pause | **Suspend/resume must not interfere with the existing throttle/pause state machine.** D-01..D-03 explicitly forbid that interaction; the monitoring loop continues unmodified during the shock window. |
| Max 2 models loaded simultaneously | No model loading changes. |
| Miro API 2s batching (N/A this phase) | Not touched. |
| Python 3.11+ strict typing | `ShockInputScreen(Screen[str \| None])`, new methods use full type annotations, `mypy --strict` must pass. |
| `uv` package manager, `pytest-asyncio` | No new dependencies. Tests use existing `pyproject.toml [tool.pytest.ini_options] asyncio_mode = "auto"` config. |
| `ollama-python >=0.6.1`, `textual >=8.1.1`, `neo4j >=5.28`, `pydantic`, `pydantic-settings`, `structlog`, `httpx` | All already in `pyproject.toml`. No new dependencies. |
| GSD Workflow enforcement | Phase 26 work proceeds through `/gsd:execute-phase`. |

**CLAUDE.md does not contradict any CONTEXT.md decision.** Hardware target (M1 Max 64GB) is honored because the shock pause actually *reduces* pressure (zero agents running while the user types).

## Standard Stack

### Core
| Library | Version (verified from `uv.lock`) | Purpose | Why Standard |
|---------|------------------------------------|---------|--------------|
| `textual` | 8.1.1 (released 2026-03-10) | Dashboard + modal overlay (`Screen`, `Container`, `Static`, `Input`, `push_screen`, `dismiss`, `set_interval`) | Already the AlphaSwarm TUI framework since Phase 9; `Screen[T]` generic + `dismiss(value)` + `push_screen(screen, callback)` is the officially-documented modal pattern |
| `neo4j` (Python async driver) | 5.28.3 (released 2026-01-12) | Async session `execute_write` for `ShockEvent` persistence | Already the AlphaSwarm graph layer since Phase 4; session-per-method is the established convention |
| `asyncio` | stdlib (Python 3.11+) | `Event` (resume gate) + `Queue(maxsize=1)` (shock channel) | Zero dependencies; already used extensively (`_rationale_queue`, `_resume_event`, `_adjustment_lock`) |
| `structlog` | already pinned | Log `shock_submitted`, `governor_suspended`, `governor_resumed`, `shock_event_written` events | Project-wide observability convention |
| `pytest-asyncio` | >=0.24.0 (dev) | Async test runner with `asyncio_mode = "auto"` | Already the project test runner |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uuid` (stdlib) | — | Generate `shock_id` | Used in existing `graph.py:create_cycle` — reuse the `str(uuid.uuid4())` pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff — Why Rejected |
|------------|-----------|-------------------------|
| `asyncio.Queue(maxsize=1)` as bridge | Textual reactive attributes, `App.post_message`, separate channel | D-04/D-06 locks StateStore as the single bridge — avoiding a second channel preserves the existing test seam and mental model |
| Shock via `stop_monitoring()`/`start_monitoring()` | Previously-considered pattern | Explicitly forbidden by D-03 — this drains the pool, resets state to RUNNING, and risks an immediate false THROTTLED on restart (root cause of the 4-bug governor deadlock, 2026-04-03) |
| Inline docked shock widget | Always-visible input row | D-15 forbids — inline docking would contaminate the normal dashboard chrome and break the Phase 9 "one-purpose-at-a-time" aesthetic |
| Separate `ShockEvent.PRECEDES.Decision` edge in Phase 26 | Graph traversal from Phase 27 | Explicitly deferred (Deferred Ideas) — keep schema minimal |
| Multi-shock per cycle (`Queue(maxsize=N)`) | — | Explicitly deferred — `maxsize=1` is the current scope |

**Installation:** No new packages required.

**Version verification:** `textual 8.1.1` and `neo4j 5.28.3` confirmed from `uv.lock` (HIGH confidence — read directly from lockfile in this session).

## Architecture Patterns

### Recommended Project Structure

Phase 26 adds code **in place** to existing modules — no new files. Reasoning: each piece is ≤ 50 lines and every piece has a canonical home (governor → governor.py, state → state.py, orchestration → simulation.py, UI → tui.py, persistence → graph.py).

```
src/alphaswarm/
├── governor.py    # ADD: suspend(), resume() methods near acquire() (~line 200)
├── state.py       # ADD: _shock_queue, _shock_window, accessors near _rationale_queue (~line 109)
├── simulation.py  # EDIT: inject shock window at inter-round gaps (~line 843, ~line 974)
├── tui.py         # ADD: ShockInputScreen class after RumorInputScreen (~line 450)
│                  # EDIT: _poll_snapshot() detection (~line 851)
└── graph.py       # ADD: write_shock_event() method + SCHEMA_STATEMENTS index (~line 70)
tests/
├── test_governor.py      # ADD: TestSuspendResume class — suspend blocks acquire, resume unblocks, state machine untouched
├── test_state.py         # ADD: shock queue put/get roundtrip, shock_window set/clear
├── test_simulation.py    # ADD: inter-round shock triggers dispatch_wave with effective_message
├── test_tui.py           # ADD: ShockInputScreen pushed when shock_window set, Enter dismisses with text, Esc dismisses with None
└── test_graph.py         # ADD: write_shock_event calls execute_write with ShockEvent CREATE Cypher
```

### Pattern 1: Governor Suspend/Resume (Event.clear/set, state-machine bypass)
**What:** Two one-line methods that manipulate *only* `_resume_event`, bypassing all state-machine logic.

**When to use:** Whenever a caller-driven pause is needed that must NOT look like a memory-pressure pause to the state machine.

**Existing primitive:** `_resume_event: asyncio.Event` (`governor.py:188`) is already the gate `acquire()` waits on (`governor.py:203`). D-01/D-02 say: just flip it from a new caller, don't touch `_state`.

**Example (source: `governor.py` lines 188, 203-205 for existing primitive; D-01..D-03 for new methods):**
```python
# governor.py — add after acquire()/release()
def suspend(self) -> None:
    """Block new acquire() calls by clearing the resume event.

    Per D-01..D-03: does NOT touch self._state, does NOT interact with the
    monitoring loop, does NOT call stop_monitoring(). The monitor keeps
    running; its state-machine logic continues unaffected.

    Safe to call while monitor loop is alive. Idempotent (clearing an
    already-cleared event is a no-op).
    """
    self._resume_event.clear()
    log.info("governor suspended for shock window")

def resume(self) -> None:
    """Unblock new acquire() calls by setting the resume event.

    Per D-02: mirror of suspend(). Idempotent.
    """
    self._resume_event.set()
    log.info("governor resumed from shock window")
```

**Critical invariant:** `suspend()` must never be called while the governor state is `PAUSED` or `CRISIS`, because in that case the state-machine has *already* cleared `_resume_event` and will re-set it when pressure subsides. If the shock caller then calls `resume()`, it would bypass the state machine and let agents through during a real pressure event. **Phase 26 avoids this entirely by calling `suspend()` only at inter-round gaps when no agents are running and the governor is in `RUNNING` state** (see Pitfall 1).

### Pattern 2: StateStore Queue + Event (copy of `_rationale_queue`)
**What:** One `asyncio.Queue(maxsize=1)` for the shock payload, one `asyncio.Event` as the "overlay visible" flag.

**When to use:** Any simulation↔TUI handshake where simulation waits for a single user decision.

**Example (source: `state.py:109` `_rationale_queue` pattern; D-04..D-07):**
```python
# state.py — add to StateStore.__init__
self._shock_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)
self._shock_window: asyncio.Event = asyncio.Event()

# add accessor methods
async def request_shock(self) -> None:
    """Signal the TUI that a shock window is open. Called by simulation."""
    self._shock_window.set()

async def close_shock_window(self) -> None:
    """Signal the TUI that the shock window is closed. Called after resume."""
    self._shock_window.clear()

def is_shock_window_open(self) -> bool:
    """Read by TUI _poll_snapshot() to decide whether to push ShockInputScreen."""
    return self._shock_window.is_set()

async def submit_shock(self, shock_text: str | None) -> None:
    """Called by TUI when ShockInputScreen dismisses. Non-blocking put."""
    await self._shock_queue.put(shock_text)

async def await_shock(self) -> str | None:
    """Called by simulation — blocks until TUI submits (or dismisses)."""
    return await self._shock_queue.get()
```

**Why `maxsize=1`:** one shock per inter-round gap, per CONTEXT.md's Deferred Ideas (multi-shock is Phase 27+).

### Pattern 3: Inter-Round Shock Gap in `run_simulation()`
**What:** At each inter-round boundary, suspend governor → open shock window → await queue → (persist if non-None) → build effective_message → resume governor → dispatch shocked round.

**Where:** `simulation.py` between `on_round_complete` callback and the next `set_phase()` call:
- R1→R2 gap: between line ~839 (`round1` callback fire) and line ~850 (`phase = SimulationPhase.ROUND_2`)
- R2→R3 gap: between line ~971 (`round2` callback fire) and line ~974 (`phase = SimulationPhase.ROUND_3`)

**Example (shape only — planner will finalize):**
```python
# After Round 1 callback fires, before "phase = SimulationPhase.ROUND_2"
shock_text_r2: str | None = None
if state_store is not None:
    governor.suspend()
    try:
        await state_store.request_shock()
        shock_text_r2 = await state_store.await_shock()
        await state_store.close_shock_window()
        if shock_text_r2:
            await graph_manager.write_shock_event(
                cycle_id=cycle_id,
                shock_text=shock_text_r2,
                injected_before_round=2,
            )
    finally:
        governor.resume()

# Build effective message for Round 2
effective_message_r2 = f"{rumor}\n\n[BREAKING] {shock_text_r2}" if shock_text_r2 else rumor

# ... later, in dispatch_wave for Round 2:
round2_wave_decisions = await dispatch_wave(
    personas=worker_configs,
    governor=governor,
    client=ollama_client,
    model=worker_alias,
    user_message=effective_message_r2,  # <-- only change vs. current code
    settings=settings.governor,
    peer_contexts=round2_peer_contexts,
    state_store=state_store,
)
```

**Critical ordering (D-05):** `suspend()` **before** `request_shock()`, and `resume()` **inside the finally** — otherwise an exception between request and await would leave the governor permanently suspended.

### Pattern 4: TUI Modal via sync `_poll_snapshot()` → `push_screen` → callback
**What:** The 200ms sync timer reads `is_shock_window_open()`, pushes `ShockInputScreen` with a callback, and the callback puts the result onto the StateStore queue.

**Why sync push works:** The existing `action_open_interview` at `tui.py:779-787` is a sync method that calls `self.push_screen(InterviewScreen(...))` — proving that synchronous screen push is a first-class pattern in this codebase. Textual's `push_screen(screen, callback)` is documented and verified via Textual docs.

**Example (source: `tui.py:684`, `tui.py:779-787`, and Textual docs for callback form):**
```python
# tui.py — inside _poll_snapshot() (~ line 851)
# Append near the end, after the existing bracket panel update:
if self._shock_window_was_open is False and self.app_state.state_store.is_shock_window_open():
    # Rising-edge detection — avoid pushing the screen twice
    self._shock_window_was_open = True
    next_round = snapshot.round_num + 1  # round_num is the just-completed round
    self.push_screen(
        ShockInputScreen(next_round=next_round),
        self._on_shock_submitted,
    )
elif self._shock_window_was_open and not self.app_state.state_store.is_shock_window_open():
    # Window closed by simulation (after queue drain) — reset edge latch
    self._shock_window_was_open = False

# new callback method on the App class
def _on_shock_submitted(self, shock_text: str | None) -> None:
    """Called when ShockInputScreen dismisses. Puts result on StateStore queue."""
    # Fire-and-forget: StateStore.submit_shock is async but we're in sync timer context
    self.run_worker(
        self.app_state.state_store.submit_shock(shock_text),
        exclusive=False,
        exit_on_error=True,
    )
```

**Edge latch:** The `_shock_window_was_open` boolean is required to prevent `_poll_snapshot` (running every 200ms) from pushing a new `ShockInputScreen` on every tick while the original is still open. This is a classic rising-edge detection and is critical — skipping it is Pitfall 2 below.

### Pattern 5: Neo4j Write via `execute_write`
**What:** New `write_shock_event()` method follows the exact same pattern as `create_cycle` at `graph.py:149-173`.

**Example (source: `graph.py:149-173`, `graph.py:269-326` for the param-dict + `execute_write` convention):**
```python
# graph.py — add a SCHEMA_STATEMENTS entry first:
SCHEMA_STATEMENTS: list[str] = [
    # ... existing entries ...
    "CREATE INDEX shock_cycle_idx IF NOT EXISTS FOR (s:ShockEvent) ON (s.cycle_id)",
]

# Add method to GraphStateManager
async def write_shock_event(
    self,
    cycle_id: str,
    shock_text: str,
    injected_before_round: int,
) -> str:
    """Persist a ShockEvent node linked to its Cycle via HAS_SHOCK.

    Per D-11..D-13. Uses session-per-method pattern consistent with
    create_cycle() and write_decisions(). Raises Neo4jWriteError on
    driver errors (same as write_decisions).
    """
    shock_id = str(uuid.uuid4())
    try:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(
                self._write_shock_event_tx,
                shock_id,
                cycle_id,
                shock_text,
                injected_before_round,
            )
    except Neo4jError as exc:
        raise Neo4jWriteError(
            f"Failed to write shock_event for cycle {cycle_id}",
            original_error=exc,
        ) from exc
    self._log.info(
        "shock_event_written",
        shock_id=shock_id,
        cycle_id=cycle_id,
        injected_before_round=injected_before_round,
    )
    return shock_id

@staticmethod
async def _write_shock_event_tx(
    tx: AsyncManagedTransaction,
    shock_id: str,
    cycle_id: str,
    shock_text: str,
    injected_before_round: int,
) -> None:
    await tx.run(
        """
        MATCH (c:Cycle {cycle_id: $cycle_id})
        CREATE (se:ShockEvent {
            shock_id: $shock_id,
            cycle_id: $cycle_id,
            shock_text: $shock_text,
            injected_before_round: $injected_before_round,
            created_at: datetime()
        })
        CREATE (c)-[:HAS_SHOCK]->(se)
        """,
        shock_id=shock_id,
        cycle_id=cycle_id,
        shock_text=shock_text,
        injected_before_round=injected_before_round,
    )
```

### Anti-Patterns to Avoid

- **Do not call `stop_monitoring()` / `start_monitoring()` to pause for shock.** D-03 forbids. This is the pattern that caused bugs 1, 4, 5 in the 2026-04-03 governor deadlock investigation — state reset, TokenPool drain, monitor task death, and stuck `_resume_event` all stacked up.
- **Do not touch `_state`, `_crisis_start`, or `_consecutive_green_checks` in `suspend()`/`resume()`.** Leave the state machine alone — it is the memory-pressure authority and shock is an authoring pause, not a pressure event.
- **Do not add a second inter-task channel** (e.g., `App.post_message` to simulation). D-06 locks StateStore as the single bridge.
- **Do not block `_poll_snapshot()` waiting for the user** — it runs every 200ms on the Textual event loop and the dashboard must remain responsive. The push-screen-with-callback pattern keeps the timer non-blocking.
- **Do not compute `effective_message` inside `dispatch_wave` or `worker.infer`** — D-09 forbids. All shock logic lives in `run_simulation()`.
- **Do not push `ShockInputScreen` on every tick.** Use the `_shock_window_was_open` edge latch pattern (Pitfall 2).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async pause/resume gate | Custom `asyncio.Lock`-based gate | `asyncio.Event` (already used by `_resume_event`) | Event is the single-purpose stdlib primitive for this exact pattern; Lock is for mutual exclusion, not broadcast |
| Bounded single-slot mailbox | Custom `Future` handoff | `asyncio.Queue(maxsize=1)` (already used by `_rationale_queue`) | Queue gives you put/get back-pressure + explicit blocking semantics with one line of code |
| Inter-process-ish TUI↔simulation channel | Any of: Textual messages, reactive attrs, callbacks into simulation | StateStore (the existing bridge) | Adding a second channel doubles the mental model and breaks the test seam; D-06 locks this |
| Modal overlay | Custom `Container` with manual show/hide | Textual `Screen` subclass + `push_screen`/`dismiss` | `Screen` is the first-class modal primitive, already used by `RumorInputScreen` and `InterviewScreen` |
| UUID generation | Custom counter or timestamp | `uuid.uuid4()` | Already the `create_cycle` / `write_decisions` convention |
| Neo4j driver session management | Manual driver-level transactions | `session.execute_write(tx_fn, ...)` | Neo4j 5.x async driver's managed transaction function — idempotent retries, automatic commit/rollback; already the project standard |
| Datetime stamp on graph nodes | Python `datetime.now()` passed as param | Neo4j Cypher `datetime()` inside CREATE | Already the convention for `created_at` in `create_cycle` and others — keeps timestamp consistent with DB clock |

**Key insight:** Every primitive Phase 26 needs already exists in the codebase (`asyncio.Event`, `asyncio.Queue`, `Screen[T]`, `execute_write`, `uuid.uuid4()`). This is a copy-paste-and-rename phase, not a design-from-scratch phase. The plan should be small and the risk is entirely in **not deviating** from D-01..D-17.

## Runtime State Inventory

Phase 26 is additive (new code + new schema) and does not rename, refactor, or migrate any existing runtime state. This section is included for completeness but all categories are empty.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified by `grep -r "shock\|Shock\|SHOCK" src/` returning zero hits. No existing ShockEvent / shock_queue / shock field anywhere to migrate or rename. | None |
| Live service config | None — no external services configured. Ollama + Neo4j are the only runtime services and neither has pre-existing "shock" config. | None |
| OS-registered state | None — no OS-level task/service registrations used by the project (no launchd, no systemd, no Task Scheduler). | None |
| Secrets/env vars | None — no env vars reference shock. `pyproject.toml` and `.env` (none found) have no shock-related keys. | None |
| Build artifacts | None — pure Python source additions to existing modules; `uv` will rebuild the wheel as usual, no stale artifacts carry the new names. | None |

**Verified via:** `grep -r` across `src/` showed zero pre-existing shock references. Schema changes are strictly additive (new label, new edge type, new index) and existing schema is untouched.

## Common Pitfalls

### Pitfall 1: `suspend()` during PAUSED/CRISIS state corrupts the resume gate
**What goes wrong:** If `run_simulation()` calls `governor.suspend()` while the governor's state machine has *already* cleared `_resume_event` due to memory pressure (PAUSED or CRISIS), then the shock code's `governor.resume()` will set `_resume_event` and release agents — even though memory pressure has not actually subsided. The state machine will re-clear the event on its next tick, but there is a race window.

**Why it happens:** `suspend()`/`resume()` bypass the state machine (D-01). If the state machine happens to have the same gate cleared for its own reasons, `resume()` makes a decision the state machine did not authorize.

**How to avoid:**
- At each inter-round gap, assert `governor.state == GovernorState.RUNNING` before calling `suspend()`. If not RUNNING, skip the shock window entirely (log a warning and continue).
- Inter-round gaps already have zero active agents (the previous round's `dispatch_wave` has returned and all slots are released), so this check should normally pass.
- Do NOT put the shock window inside a round or inside `dispatch_wave`.

**Warning signs:** Logs show `governor state transition` (from the state machine) and `governor resumed from shock window` (from `resume()`) interleaved. Any test that sees both transitions within the same round boundary should fail.

**Test requirement:** `test_governor.py` — `test_suspend_resume_during_running_is_safe`, `test_suspend_does_not_modify_state`, `test_resume_does_not_modify_state`.

### Pitfall 2: `_poll_snapshot()` pushes `ShockInputScreen` every 200ms tick
**What goes wrong:** Without a rising-edge latch, every 200ms tick while `_shock_window.is_set()` pushes a new `ShockInputScreen` on top of the previous one. The user types into the newest overlay, the queue gets flooded with `submit_shock` calls, the simulation drains only the first and leaves zombies.

**Why it happens:** `_poll_snapshot` is a level-triggered timer, but screen push semantics expect an edge-triggered event.

**How to avoid:** Keep a `self._shock_window_was_open: bool = False` instance attribute. Push only on the rising edge (`False → True`), reset the latch on the falling edge (`True → False`) when the simulation clears the event. Shown in Pattern 4 code example above.

**Warning signs:** Pilot-based TUI integration test shows more than one `ShockInputScreen` on the screen stack, or `submit_shock` is awaited more than once per round.

**Test requirement:** `test_tui.py` — `test_shock_screen_pushed_once_per_window`, `test_shock_screen_not_re_pushed_while_open`.

### Pitfall 3: `run_simulation()` path without `state_store` leaves governor suspended
**What goes wrong:** `run_simulation()` accepts `state_store: StateStore | None = None`. If `state_store is None` (e.g., CLI-only non-TUI invocation), the shock window cannot be opened — but if a naive implementation unconditionally calls `governor.suspend()` and `await state_store.await_shock()`, the first raises AttributeError or the second deadlocks forever.

**Why it happens:** TUI and non-TUI paths share the same `run_simulation()` function.

**How to avoid:**
- Wrap the entire shock block in `if state_store is not None:`. Non-TUI paths bypass the shock window and behave identically to pre-Phase-26 code (zero behavioral change for CLI `report` / non-interactive runs).
- Use `try: ... finally: governor.resume()` so that any exception inside the shock block still releases the gate.

**Warning signs:** Any non-TUI test (`test_simulation.py` running without `state_store=StateStore()`) hangs or raises AttributeError.

**Test requirement:** `test_simulation.py` — `test_run_simulation_without_state_store_skips_shock_window`, `test_run_simulation_with_state_store_opens_and_closes_shock_window`.

### Pitfall 4: Textual `push_screen` callback runs on main thread but our submit is async
**What goes wrong:** `StateStore.submit_shock()` is `async def` (it awaits `queue.put`). A plain callback `def _on_shock_submitted(self, shock_text): self.state_store.submit_shock(shock_text)` returns a coroutine object that never gets scheduled — the queue never gets the item — the simulation hangs forever.

**Why it happens:** Textual callbacks are plain sync functions, but `asyncio.Queue.put` with a bounded queue may block if full (even `maxsize=1`, if two submits raced).

**How to avoid:** Use `self.run_worker(self.state_store.submit_shock(text), exclusive=False, exit_on_error=True)` to schedule the coroutine on Textual's worker manager. Alternatively, use `queue.put_nowait(text)` inside a sync wrapper — safe here because `maxsize=1` and we guarantee only one pending shock at a time (by the edge latch in Pitfall 2). The `put_nowait` approach is simpler and is what `StateStore.push_rationale()` (`state.py:155-162`) does.

**Warning signs:** Simulation logs `governor_suspended for shock window` but no `governor_resumed` message ever appears; the TUI freezes after the first inter-round overlay.

**Test requirement:** `test_tui.py` — `test_shock_submit_enqueues_text_on_state_store`, `test_shock_dismiss_enqueues_none_on_state_store`.

### Pitfall 5: `effective_message` mutates `rumor` used elsewhere in the round
**What goes wrong:** If the planner reassigns `rumor = f"{rumor}\n\n[BREAKING] ..."`, later code in the same round that reads `rumor` (e.g., the log line `round_dispatch_start` at `simulation.py:873` shows no rumor today, but post-simulation narrative generation at `_generate_decision_narratives` might) gets a corrupted base rumor.

**Why it happens:** Shadowing the `rumor` variable local is convenient but fragile.

**How to avoid:** Use a new local `effective_message_r2` / `effective_message_r3` per D-08 and only pass the new name to `dispatch_wave(user_message=...)`. Leave `rumor` untouched. This also makes it easy to reason about Round 3 if both rounds can be shocked.

**Warning signs:** Post-simulation report or narrative includes the `[BREAKING] ...` suffix on the base rumor. Interview mode (Phase 14) loads the original rumor from Neo4j `(c:Cycle).seed_rumor` — if that becomes the shocked version, the whole downstream is corrupted.

**Test requirement:** `test_simulation.py` — `test_shock_does_not_mutate_base_rumor`, `test_interview_context_uses_unshocked_rumor`.

### Pitfall 6: Governor deadlock re-regression (historical context)
**What goes wrong:** 2026-04-03 investigation found 7 bugs in governor lifecycle that caused simulation to hang after Round 1. Fixes at commits 9bd6dfa and 85cade8 landed: `stop_monitoring()` full reset, `_on_monitor_done` done callback to wake stuck agents, dead-monitor check moved after `_resume_event.wait()`, TokenPool reset, keep_alive on worker, model load timing.

**Why it matters to Phase 26:** Any code in this phase that causes monitor task death (e.g., raising inside the state machine, calling `stop_monitoring()` from a non-owner task) would re-deadlock the simulation with the exact same symptom — Round 2 never starts. D-03 is specifically to avoid this regression.

**How to avoid:** Exactly follow D-01..D-03. Do not call `stop_monitoring()`. Do not raise from `suspend()`/`resume()`. Verify test_governor.py adds a `TestSuspendResume` class that exercises both methods under an active `_monitor_loop`.

**Warning signs:** Any test failure in `test_governor.py::TestStopMonitoring` or `test_simulation.py::test_simulation_completes_three_rounds` after Phase 26 lands.

**Test requirement:** Regression tests from commits 9bd6dfa/85cade8 must still pass; add a new test that starts the monitor, calls `suspend()` + `resume()` multiple times, confirms `_state` and `_monitor_task` are unchanged throughout.

## Code Examples

See Patterns 1–5 above for the full verified code snippets. All are derived from existing code at cited file:line or from the official Textual documentation (HIGH confidence sources).

Additional canonical copy-paste references from this codebase:

### Existing `RumorInputScreen` template (source: `tui.py:385-450`)
Copy this class wholesale, rename to `ShockInputScreen`, change IDs from `input-container`/`as-title`/`as-subtitle`/`rumor-input`/`as-hint` to `shock-input-container`/`shock-title`/`shock-subtitle`/`shock-input`/`shock-hint`, change copy per `26-UI-SPEC.md`, accept `next_round: int` constructor arg, extend `BINDINGS` with an `action_skip_shock` handler that calls `self.dismiss(None)`.

### Existing `_rationale_queue` pattern (source: `state.py:109, 149-162`)
The `push_rationale`/`snapshot` pattern shows the exact idiomatic way to add a bounded queue + accessor methods. `_shock_queue` follows the same shape but with `maxsize=1` and a different overflow semantic (no oldest-drop — the queue should be empty most of the time).

### Existing `execute_write` pattern (source: `graph.py:269-326`, `graph.py:149-173`)
`write_decisions` + `_batch_write_decisions_tx` show the caller/static-txfunc split. `create_cycle` + `_create_cycle_tx` is the simplest shape and is the closer template for `write_shock_event`.

### Existing `push_screen` from sync timer (source: `tui.py:779-787`)
`action_open_interview` is a sync method that calls `push_screen` without a callback. `ShockInputScreen` needs the 2-arg form (with callback) — verified from Textual docs.

## State of the Art

| Old Approach (internal only) | Current Approach | When Changed | Impact |
|------------------------------|------------------|--------------|--------|
| `stop_monitoring()` + `start_monitoring()` as a pseudo-pause | `_resume_event.clear()`/`.set()` only (D-01..D-03) | 2026-04-03 (commits 9bd6dfa, 85cade8) | Eliminates bugs 1/4/5 of the 7-bug governor deadlock. This lesson is the direct origin of D-01..D-03. |
| No shock capability | D-01..D-17 implementation | Phase 26 (this phase) | First iteration of inter-round event injection |

**Deprecated/outdated:**
- In `tui.py`, the `_poll_snapshot` direct-push pattern was already used for `action_open_interview` (click-triggered). Phase 26 extends the same pattern with a timer-driven trigger — no new pattern is introduced.
- No external Textual API changes are needed — `Screen[T | None]`, `push_screen(screen, callback)`, `dismiss(value)` are all stable in 8.1.1 (verified).

## Open Questions

1. **Should Round 1 be shockable?** CONTEXT.md's Claude's Discretion flags this as "likely not" (no peer context to contrast). Phase 27 analysis is supposed to confirm.
   - What we know: Round 1 has no peer context, so shocking it is just changing the initial rumor — which the user could have done by typing a different rumor in `RumorInputScreen` to begin with.
   - What's unclear: Whether a product intuition like "I want to see how agents react if the rumor *evolves* before Round 1" has any merit.
   - Recommendation: **Do not enable Round 1 shock in Phase 26.** Only implement shock at R1→R2 and R2→R3 gaps. Document the decision in the plan.

2. **Should the shock window time out if the user walks away?** Currently, `await state_store.await_shock()` blocks forever.
   - What we know: The governor is suspended; memory is fine; no harm in waiting indefinitely.
   - What's unclear: Is a long-running sim with an unattended shock window a UX anti-pattern? (It may be on large displays where the user forgets.)
   - Recommendation: **No timeout in Phase 26.** The user can always press Esc to dismiss (D-07). Adding a timer belongs in Phase 27 if usage data suggests it's needed.

3. **Is the next round number passed as `snapshot.round_num + 1`?** The subtitle copy is `"Shock the swarm before Round {N}"`. `round_num` at the R1→R2 gap is still 1 (simulation hasn't called `set_round(2)` yet because that's inside the Round 2 block).
   - What we know: At the moment `state_store.request_shock()` is called, the last completed round is `snapshot.round_num`, and the next round is `snapshot.round_num + 1`.
   - What's unclear: Whether the simulation should explicitly pass the next round number through the StateStore (e.g., `state_store.request_shock(next_round=2)`) or whether the TUI should compute it.
   - Recommendation: **Simulation passes `next_round` via an explicit StateStore method `request_shock(next_round: int)`** — cleaner than computing it in the TUI and bakes the correct value at the source.

4. **Should `write_shock_event` happen before or after `resume()`?** Pattern 3 above writes before resume (inside `try`). Alternative: write after resume for minimum suspend duration.
   - What we know: Neo4j write is async and typically < 50ms. Suspend duration is dominated by the user typing, not the write.
   - What's unclear: Whether an error in the Neo4j write should block the round (current pattern) or just log and continue.
   - Recommendation: **Write before resume, but catch `Neo4jWriteError` and continue.** Surface the error via `notify` on the TUI. Losing a shock log is a degraded state, but blocking Round 2 is worse.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3.11+ | Everything (type annotations, `asyncio.TaskGroup`, `ExceptionGroup`) | Yes (assumed by project) | — | — |
| `textual >= 8.1.1` | `ShockInputScreen`, `push_screen(screen, callback)`, `dismiss(value)`, `set_interval` | Yes (installed) | 8.1.1 (verified in `uv.lock`) | — |
| `neo4j >= 5.28` async driver | `write_shock_event` session.execute_write | Yes (installed) | 5.28.3 (verified in `uv.lock`) | — |
| Running Neo4j instance (Docker or local) | Runtime `ensure_schema` + write | Same as current project baseline | — | Existing `test_graph.py` mocks the driver; unit tests don't need a live instance |
| `structlog`, `pytest`, `pytest-asyncio` | Logging + tests | Yes (installed) | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

**Skip condition not met:** Phase 26 has runtime dependencies on Neo4j and Textual, so the audit is not skipped.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio >= 0.24.0 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `testpaths = ["tests"]` |
| Quick run command | `uv run pytest tests/test_governor.py tests/test_state.py tests/test_graph.py tests/test_tui.py tests/test_simulation.py -x` |
| Full suite command | `uv run pytest -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHOCK-01 | User can type into `ShockInputScreen` and submit; screen dismisses with text | unit (Textual `run_test` + `Pilot`) | `uv run pytest tests/test_tui.py::test_shock_input_screen_enter_dismisses_with_text -x` | ❌ Wave 0 |
| SHOCK-01 | Pressing Esc dismisses with `None` | unit (Textual `run_test` + `Pilot`) | `uv run pytest tests/test_tui.py::test_shock_input_screen_esc_dismisses_with_none -x` | ❌ Wave 0 |
| SHOCK-01 | `_poll_snapshot()` pushes `ShockInputScreen` when shock window opens | unit (Textual `run_test` + fake StateStore) | `uv run pytest tests/test_tui.py::test_poll_snapshot_pushes_shock_screen_on_window_open -x` | ❌ Wave 0 |
| SHOCK-01 | `ShockInputScreen` is pushed at most once per window (edge-latch) | unit (Pilot) | `uv run pytest tests/test_tui.py::test_shock_screen_pushed_once_per_window -x` | ❌ Wave 0 |
| SHOCK-02 | `governor.suspend()` blocks subsequent `acquire()` calls | unit | `uv run pytest tests/test_governor.py::TestSuspendResume::test_suspend_blocks_acquire -x` | ❌ Wave 0 |
| SHOCK-02 | `governor.resume()` unblocks pending `acquire()` calls | unit | `uv run pytest tests/test_governor.py::TestSuspendResume::test_resume_unblocks_acquire -x` | ❌ Wave 0 |
| SHOCK-02 | `suspend()`/`resume()` do not modify `_state`, `_crisis_start`, `_consecutive_green_checks`, or `TokenPool` | unit | `uv run pytest tests/test_governor.py::TestSuspendResume::test_suspend_does_not_touch_state_machine -x` | ❌ Wave 0 |
| SHOCK-02 | `suspend()` does NOT interfere with an active `_monitor_loop` (loop keeps running and `_state` stays RUNNING under GREEN pressure) | unit | `uv run pytest tests/test_governor.py::TestSuspendResume::test_monitor_loop_continues_during_suspend -x` | ❌ Wave 0 |
| SHOCK-02 | `run_simulation()` passes `effective_message` with `[BREAKING]` prefix to Round 2 `dispatch_wave` when a shock was submitted | unit (mocked `dispatch_wave`) | `uv run pytest tests/test_simulation.py::test_shock_injected_into_round2_user_message -x` | ❌ Wave 0 |
| SHOCK-02 | `run_simulation()` passes unmodified `rumor` to Round 2 when no shock submitted (Esc / empty) | unit | `uv run pytest tests/test_simulation.py::test_round2_unchanged_when_no_shock -x` | ❌ Wave 0 |
| SHOCK-02 | `run_simulation()` without a `state_store` skips the shock window and still completes | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_without_state_store_skips_shock -x` | ❌ Wave 0 |
| SHOCK-02 | Shock does not mutate base `rumor` variable; subsequent rounds and downstream code see the original | unit | `uv run pytest tests/test_simulation.py::test_shock_does_not_mutate_base_rumor -x` | ❌ Wave 0 |
| SHOCK-03 | `write_shock_event()` calls `session.execute_write` with correct `CREATE (se:ShockEvent {...})` + `(c)-[:HAS_SHOCK]->(se)` | unit (`mock_driver`) | `uv run pytest tests/test_graph.py::test_write_shock_event_creates_node_and_edge -x` | ❌ Wave 0 |
| SHOCK-03 | `write_shock_event()` returns a UUID4 string `shock_id` | unit | `uv run pytest tests/test_graph.py::test_write_shock_event_returns_uuid -x` | ❌ Wave 0 |
| SHOCK-03 | `write_shock_event()` wraps Neo4jError in `Neo4jWriteError` | unit | `uv run pytest tests/test_graph.py::test_write_shock_event_wraps_driver_errors -x` | ❌ Wave 0 |
| SHOCK-03 | `ensure_schema()` applies the new `CREATE INDEX shock_cycle_idx ...` statement | unit | `uv run pytest tests/test_graph.py::test_ensure_schema_includes_shock_cycle_index -x` | ❌ Wave 0 |
| SHOCK-03 | StateStore `shock_queue` round-trip: put/get with text and with None | unit | `uv run pytest tests/test_state.py::test_shock_queue_roundtrip -x` | ❌ Wave 0 |
| SHOCK-03 | StateStore `shock_window` set/clear reflected in `is_shock_window_open()` | unit | `uv run pytest tests/test_state.py::test_shock_window_event_reflects_state -x` | ❌ Wave 0 |
| Cross-cutting | End-to-end: TUI → shock submit → simulation reads queue → round 2 dispatch → Neo4j write (mocked Ollama, mocked Neo4j driver) | integration | `uv run pytest tests/test_simulation.py::test_end_to_end_shock_round2 -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_governor.py tests/test_state.py tests/test_graph.py tests/test_tui.py tests/test_simulation.py -x` (5 files, ~15 seconds in a dev loop)
- **Per wave merge:** `uv run pytest -x` (full suite)
- **Phase gate:** Full suite green + `uv run mypy src/alphaswarm/` green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_governor.py` — new `TestSuspendResume` class with 4 tests (blocks, unblocks, state-machine-untouched, monitor-loop-continues)
- [ ] `tests/test_state.py` — shock queue + shock window tests (2 tests)
- [ ] `tests/test_graph.py` — `write_shock_event` tests (4 tests) + schema index test
- [ ] `tests/test_tui.py` — `ShockInputScreen` tests (5 tests via `Pilot` + fake StateStore fixture)
- [ ] `tests/test_simulation.py` — shock injection path tests (6 tests) including end-to-end integration
- [ ] No new framework install required — `pytest`, `pytest-asyncio`, and `textual.run_test` all already in use
- [ ] No new fixtures required beyond a `mock_state_store` helper (can go in `tests/conftest.py` if reused)

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/governor.py` — Full file read in this session. Confirms `_resume_event` at line 188-189 (initialized set), `acquire()` at 193-206 (waits on event), `_update_resume_event()` at 402-407 (state-machine authority), `_on_monitor_done` at 239-247 (unblocks stuck waiters), `stop_monitoring()` full reset at 249-272. All D-01..D-03 reasoning verified.
- `src/alphaswarm/state.py` — Full file read in this session. `_rationale_queue` pattern at line 108-109 (init), 149-162 (put with drop-oldest) confirmed as the copy-paste template for `_shock_queue`. `StateSnapshot` is frozen dataclass; shock fields can stay mutable on `StateStore` (don't need to be in snapshot).
- `src/alphaswarm/simulation.py` — Read the `run_simulation` signature (line 718), the R1→R2 gap (lines ~830-853), and the R2→R3 gap (lines ~970-1000). Confirmed `dispatch_wave(user_message=rumor, ...)` is the single-point prompt injection call at lines 886-895 (R2) and 1004-1013 (R3).
- `src/alphaswarm/tui.py` — Read lines 385-450 (`RumorInputScreen`), 684-697 (screen push on startup), 779-787 (`action_open_interview` sync push), 851-914 (`_poll_snapshot`). Confirmed all CONTEXT.md line references.
- `src/alphaswarm/graph.py` — Read lines 60-70 (SCHEMA_STATEMENTS), 101-106 (session + ensure_schema pattern), 149-173 (create_cycle as simplest write template), 269-379 (write_decisions + txfn pattern).
- `src/alphaswarm/batch_dispatcher.py` — Full file read. Confirmed `user_message` pass-through at lines 67-68, `dispatch_wave` signature at 81-92, TaskGroup at 135-151. D-09 verified.
- `src/alphaswarm/worker.py` — Full file read. Confirmed `messages` list assembly at 87-92 using `user_message`. No changes needed.
- `pyproject.toml` — Confirmed dependency versions and pytest config.
- `uv.lock` — Confirmed `textual 8.1.1` (2026-03-10 release) and `neo4j 5.28.3` (2026-01-12 release).
- `tests/test_governor.py`, `tests/test_tui.py`, `tests/test_graph.py` — Confirmed existing test patterns: `MagicMock` driver, `app.run_test(size=(...))` + `Pilot`, `pytest-asyncio` auto mode, class-based grouping.
- Textual official docs: https://textual.textualize.io/guide/screens/ — Confirmed `ModalScreen[T]` / `Screen[T]` generic dismiss type, `push_screen(screen, callback)` callback form, `dismiss(value)` semantics, `push_screen_wait()` alternative for async context.
- `.planning/phases/26-shock-injection-core/26-CONTEXT.md` — All D-01..D-17 locked decisions.
- `.planning/phases/26-shock-injection-core/26-UI-SPEC.md` — UI Design Contract for `ShockInputScreen` (copy/CSS/accessibility).

### Secondary (MEDIUM confidence)
- `~/.claude/projects/.../memory/bug_governor_deadlock.md` — 7-day-old memory of the 7-bug governor deadlock investigation. Flagged as point-in-time; verified against current `governor.py` code (all fixes present at expected lines), so MEDIUM-upgraded-to-HIGH for the specific claims about what D-03 is protecting against.
- Textual API reference pages (`/api/app/`, `/api/message_pump/`) — Documentation excerpts cut off before definitive `set_interval` async-support answer. Current codebase uses `set_interval(1/5, self._poll_snapshot)` with a sync `_poll_snapshot` (verified at `tui.py:696, 851`), so the project's actual usage is sync-callback only. This is sufficient for Phase 26.

### Tertiary (LOW confidence)
- None. All claims in this document are backed by either direct code read, lockfile verification, or official Textual documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — all libraries are already in `pyproject.toml` at exact versions; no new dependencies to add or verify.
- Architecture: **HIGH** — every pattern (Event gate, Queue bridge, Screen overlay, `execute_write` txfn) is a direct copy-paste from existing code in the same repo, with file:line citations verified this session.
- Pitfalls: **HIGH** — pitfalls 1, 2, 3, 5, 6 are grounded in directly-read code and the 7-day-old governor-bug memory (cross-verified against current code). Pitfall 4 (sync callback + async put) is a standard asyncio-in-sync-context gotcha, verified against how `StateStore.push_rationale` handles the same constraint.
- Phase requirements: **MEDIUM** — SHOCK-01..03 are not yet in `REQUIREMENTS.md`; the planner must add them. The inferred bodies are based on the Success Criteria in ROADMAP.md and CONTEXT.md, both of which are explicit and consistent.
- Environment availability: **HIGH** — no new external dependencies; all runtime deps already installed and version-pinned.

**Research date:** 2026-04-10
**Valid until:** 2026-05-10 (30 days — the ecosystem is stable and this phase is entirely internal; the only external risk is a Textual or Neo4j driver release that changes `push_screen`/`execute_write` semantics, which would require re-verification)

---

## Malware / Security Analysis Note

Per the environment reminder: every file read in this research session (`governor.py`, `state.py`, `simulation.py`, `tui.py`, `graph.py`, `batch_dispatcher.py`, `worker.py`, `pyproject.toml`, `config.json`, `CONTEXT.md`, `UI-SPEC.md`, `REQUIREMENTS.md`, `STATE.md`, `ROADMAP.md`, `CLAUDE.md`, `bug_governor_deadlock.md`, `test_governor.py`, `test_tui.py`, `test_graph.py`) is legitimate AlphaSwarm project code, test code, or planning documentation. Nothing read resembles malware:

- No obfuscated code, no network exfiltration, no credential harvesting, no privilege escalation, no unauthorized filesystem access outside the project root, no dynamic code evaluation of untrusted input.
- All async patterns follow standard Python asyncio and Textual idioms.
- Neo4j writes are parameterized Cypher (no string concatenation into queries); Ollama client uses the official Python library; user input flows through trimmed string handling consistent with Phase 9/14 patterns.

This research document analyzes existing code behavior and specifies how new code should be structured to comply with the user-locked decisions in CONTEXT.md. It does not modify any existing file.
