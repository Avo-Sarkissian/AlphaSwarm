# Phase 34: Replay Mode Web UI - Research

**Researched:** 2026-04-14
**Domain:** FastAPI backend state machine + Vue 3 frontend mode switching + WebSocket broadcast integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Idle ControlBar gets a "Replay" button (alongside Start). Clicking opens a **modal overlay** listing completed cycles — cycle ID (truncated), date, seed rumor preview. Radio selection + Cancel / Start Replay buttons. Modal dismisses on selection or cancel. The modal is a new `CyclePicker.vue` component mounted in `App.vue`.
- **D-02:** The modal fetches `GET /api/replay/cycles` on open (not eagerly) to keep idle state lightweight.
- **D-03:** In replay mode, the seed textarea + Start button are **replaced** (v-if) with a compact replay strip — same single-row footprint. Layout: `[■ REPLAY]` badge | cycle ID + seed rumor truncated | Round N/3 indicator | `[▶ Next]` button | `[✕ Exit]` button.
- **D-04:** The REPLAY badge is the leftmost element of the strip and lives **inside the ControlBar** (not a floating overlay). Styled distinctly (amber/orange background, monospace text).
- **D-05:** `[▶ Next]` is disabled at Round 3/3 (no wrap-around). `[✕ Exit]` calls `POST /api/replay/stop` and returns to idle state.
- **D-06:** **Manual-only stepping** — user taps `[▶ Next]` to advance one round. No auto-advance timer. Stays pinned at Round 3/3 when complete (Next button disabled, no loop).
- **D-07:** New `ReplayManager` class in `src/alphaswarm/web/replay_manager.py`. Holds `ReplayStore` instance, active `cycle_id`, current `round_num`. Mounted on `AppState` (same pattern as `SimulationManager`). Created in lifespan.
- **D-08:** `replay_start` fills in real logic: calls `graph_manager.read_full_cycle_signals(cycle_id)` to load all signals, constructs `ReplayStore`, sets round 1, updates phase to `SimulationPhase.REPLAY`, and triggers a WebSocket broadcast of the round-1 snapshot.
- **D-09:** `replay_advance` increments `round_num` on `ReplayManager` (max 3), calls `replay_store.set_round(new_round)`, and broadcasts the new snapshot through the existing `ConnectionManager.broadcast()` path.
- **D-10:** New `POST /api/replay/stop` endpoint resets `ReplayManager` to idle (clears store, resets phase). Called by `[✕ Exit]` in the frontend.
- **D-11:** The WebSocket broadcast loop reads `replay_manager.store.snapshot()` when replay is active, same tick interval as live simulation. No separate polling needed.

### Claude's Discretion

- Exact CSS styling of REPLAY badge (color palette within the amber/warning family)
- CyclePicker.vue internal layout (table vs list, truncation lengths)
- Error handling for `replay_start` when cycle_id is not found in Neo4j (return 404, frontend shows toast)
- `read_full_cycle_signals` query performance — handle gracefully with a timeout/loading state in the modal

### Deferred Ideas (OUT OF SCOPE)

- Auto-advance playback mode (2-second interval timer)
- Replay scrubber / progress bar for jumping directly to Round N
- Sharing/exporting a replay link
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WEB-06 | Post-simulation views — agent interview panel, report viewer, replay mode | Phase 34 covers the replay mode sub-requirement: cycle picker, round stepping, force graph re-render from stored Neo4j state |
| REPLAY-01 | Simulation replay from stored Neo4j state (re-render without re-inference) | All data layer methods already exist (`read_full_cycle_signals`, `ReplayStore`); this phase wires them into the web broadcast path via `ReplayManager` |
</phase_requirements>

---

## Summary

Phase 34 is an integration and wiring phase, not a greenfield build. The hard parts — `ReplayStore`, `read_full_cycle_signals`, `read_bracket_narratives_for_round`, `read_rationale_entries_for_round`, `read_completed_cycles`, and all three replay REST endpoint skeletons — are already implemented and tested. The frontend force graph already reacts to `snapshot.agent_states` changes with zero modifications needed.

The primary new work falls into two categories: (1) a backend `ReplayManager` class that mirrors `SimulationManager`'s lifecycle pattern and injects replay snapshots into the existing broadcaster path, and (2) two new Vue SFCs (`CyclePicker.vue` modal and the ControlBar replay strip) that toggle via `snapshot.value.phase === 'replay'`.

The single architectural subtlety is the broadcaster coupling: `broadcaster.py` calls `snapshot_to_json(state_store)`, which reads from `StateStore` only. The `ReplayManager` must either (a) write a `REPLAY`-phase snapshot into `StateStore` on each round transition, or (b) bypass the broadcaster and call `ConnectionManager.broadcast()` directly with a serialized `ReplayStore.snapshot()`. Decision D-08 and D-11 together establish the intended approach: the broadcaster continues to tick at 200ms; when `ReplayManager` is active, it serializes `replay_store.snapshot()` and pushes it directly via `ConnectionManager.broadcast()` on each user action (start/advance). The broadcaster loop must also be updated to use `replay_store.snapshot()` during the in-between ticks so clients do not regress to an IDLE snapshot while waiting for user interaction.

**Primary recommendation:** Add a `replay_manager: ReplayManager | None` field to `app.state`, update the broadcaster to check `app_state.replay_manager` and prefer its snapshot when active, and wire `replay_start` / `replay_advance` / `replay_stop` as full implementations. Two new Vue SFCs complete the frontend.

---

## Standard Stack

### Core (verified from codebase — no new dependencies required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | existing | REST endpoints + request context access | Already the server framework |
| asyncio | stdlib | ReplayManager concurrency guard | Matches 100% async constraint from CLAUDE.md |
| Pydantic BaseModel | existing | `ReplayStartRequest`, `ReplayStopResponse` schemas | Established pattern in all routes |
| Vue 3 Composition API | existing | `CyclePicker.vue`, ControlBar replay strip | Established frontend framework |
| `inject` / `provide` | Vue 3 stdlib | `snapshot` provided by `App.vue`, consumed by `ControlBar.vue` | Pattern already used by all sibling components |
| `ref`, `computed`, `watch` | Vue 3 stdlib | Modal state, `isReplay` computed, phase watcher | Same reactive primitives used throughout |

### No New Dependencies

This phase introduces zero new Python or npm packages. The UI-SPEC explicitly states no shadcn and no third-party component libraries. All CSS uses existing `variables.css` tokens plus 4 new tokens to be added.

**New CSS tokens to add to `frontend/src/assets/variables.css`:**
```css
/* Phase 34: Replay mode */
--color-replay: #f59e0b;
--color-replay-text: #0f1117;
--duration-modal-enter: 200ms;
--duration-modal-exit: 150ms;
```

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/alphaswarm/web/
├── replay_manager.py          # NEW — mirrors simulation_manager.py pattern
└── routes/
    └── replay.py              # MODIFY — fill in replay_start, replay_advance; add replay_stop

frontend/src/components/
├── CyclePicker.vue            # NEW — modal, fetches /api/replay/cycles on open
└── ControlBar.vue             # MODIFY — add isReplay computed + replay strip template block

frontend/src/assets/
└── variables.css              # MODIFY — add 4 new tokens

frontend/src/
└── App.vue                    # MODIFY — add showCyclePicker ref, mount <CyclePicker>
```

### Pattern 1: ReplayManager (mirrors SimulationManager)

**What:** Thin stateful wrapper holding `ReplayStore` instance, active cycle metadata, and current round. Mounted on `app.state` in lifespan. REST handlers read from `request.app.state.replay_manager`.

**When to use:** Any replay operation — start, advance, stop, snapshot query.

**Key structural insight (verified from `simulation_manager.py`):**
```python
# Source: src/alphaswarm/web/simulation_manager.py — structural mirror
class ReplayManager:
    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._store: ReplayStore | None = None
        self._cycle_id: str | None = None
        self._round_num: int = 0

    @property
    def is_active(self) -> bool:
        return self._store is not None

    async def start(self, cycle_id: str, graph_manager: GraphStateManager) -> None:
        # calls graph_manager.read_full_cycle_signals(cycle_id)
        # constructs ReplayStore
        # calls self._store.set_round(1)
        # sets state_store phase to SimulationPhase.REPLAY
        # serializes and broadcasts round-1 snapshot
        ...

    async def advance(self, connection_manager: ConnectionManager) -> int:
        # increments self._round_num (max 3)
        # calls self._store.set_round(new_round)
        # broadcasts new snapshot
        # returns new round_num
        ...

    async def stop(self) -> None:
        # clears store, resets round_num
        # resets state_store phase to SimulationPhase.IDLE
        ...
```

### Pattern 2: Broadcaster Coupling — The Critical Architecture Decision

**What:** The broadcaster (`broadcaster.py`) currently reads `StateStore` at 200ms ticks. During replay, the frontend must continue to receive snapshots between user-initiated advances so it does not flicker to IDLE.

**How it works (verified from `broadcaster.py` and decision D-11):**
The broadcaster must be made `replay_manager`-aware. When `replay_manager` is active (`is_active == True`), the broadcaster uses `replay_manager.store.snapshot()` + serializes it directly (no `drain_rationales` call since `ReplayStore` does not have a rationale queue — entries are set via `set_rationale_entries`).

**Recommended broadcaster update (in `broadcaster.py`):**
```python
# Modified snapshot_to_json to accept optional replay_manager
def snapshot_to_json(state_store: StateStore, replay_manager=None) -> str:
    if replay_manager is not None and replay_manager.is_active:
        snap = replay_manager.store.snapshot()
        d = dataclasses.asdict(snap)
        # ReplayStore.snapshot() returns rationale_entries as tuple — already set
        return json.dumps(d)
    # Existing live simulation path unchanged
    snap = state_store.snapshot()
    rationales = state_store.drain_rationales(5)
    d = dataclasses.asdict(snap)
    d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]
    return json.dumps(d)
```

The broadcaster's `start_broadcaster` function would need to accept the `replay_manager` reference. Since `replay_manager` is created in lifespan alongside the broadcaster task, this is straightforward.

**Alternative approach (simpler, no broadcaster change):** On `replay_start` and `replay_advance`, directly call `connection_manager.broadcast(serialized_json)` from the endpoint handler AND also call `state_store.set_phase(REPLAY)`. The broadcaster then sends stale IDLE snapshots between user actions — but since the `ReplayStore.snapshot()` always returns `phase='replay'`, the frontend will see the correct phase continuously because the broadcaster reads `state_store` which now has `phase=REPLAY`. The broadcaster still sends live state_store snapshots (which will have the wrong `agent_states` between rounds) — this is a problem.

**Recommended resolution:** The broadcaster must check `replay_manager.is_active`. This is the clean solution matching D-11's intent ("same tick interval as live simulation").

### Pattern 3: ControlBar v-if / v-else Toggle (verified from ControlBar.vue)

**What:** `ControlBar.vue` uses `v-if` / `v-else` and `computed` predicates to switch template blocks. The existing `isActive` computed guards the stop/shock template. Replay adds a parallel `isReplay` computed.

**Current ControlBar template structure:**
```
<textarea v-model="seedText" .../>
<button ...>Start Simulation</button>
<template v-if="isActive">
  <span>{{ phaseLabel }}</span>
  <button>Stop</button>
  <button>+Inject Shock</button>
</template>
```

**Phase 34 required template restructure:**
```
<!-- Idle mode (not isActive AND not isReplay) -->
<template v-if="!isActive && !isReplay">
  <textarea v-model="seedText" />
  <button @click="startSimulation">Start Simulation</button>
  <button @click="openCyclePicker">Replay</button>    <!-- NEW -->
</template>

<!-- Live simulation mode -->
<template v-else-if="isActive && !isReplay">
  <span>{{ phaseLabel }}</span>
  <button>Stop</button>
  <button>+Inject Shock</button>
</template>

<!-- Replay mode (NEW) -->
<template v-else-if="isReplay">
  <!-- [■ REPLAY] badge | cycle info | Round N/3 | [▶ Next] | [✕ Exit] -->
</template>
```

**Key finding:** The existing `isActive` computed is `phase !== 'idle' && phase !== 'complete'`. When `phase === 'replay'`, `isActive` is currently `true`. This means adding `isReplay` must also exclude `'replay'` from `isActive`:

```typescript
// MUST update isActive to exclude replay:
const isActive = computed(() =>
  snapshot.value.phase !== 'idle' &&
  snapshot.value.phase !== 'complete' &&
  snapshot.value.phase !== 'replay'   // <-- add this
)

const isReplay = computed(() => snapshot.value.phase === 'replay')
```

**This is a non-obvious pitfall** — failing to exclude `'replay'` from `isActive` would show both the live-mode buttons AND the replay strip simultaneously.

### Pattern 4: CyclePicker.vue as App.vue Modal

**What:** Modal mounted in `App.vue` via `v-if="showCyclePicker"`. Follows the same pattern as AgentSidebar mounting.

**How App.vue wires it (verified from App.vue):**
```typescript
// In App.vue <script setup>:
import CyclePicker from './components/CyclePicker.vue'
const showCyclePicker = ref(false)

function onOpenCyclePicker() {
  showCyclePicker.value = true
}
function onCloseCyclePicker() {
  showCyclePicker.value = false
}
function onStartReplay(cycleId: string) {
  showCyclePicker.value = false
  // POST /api/replay/start/{cycleId} — or emit to ControlBar
}
```

**Event flow:** `ControlBar` emits `open-cycle-picker` → `App.vue` sets `showCyclePicker = true` → `CyclePicker` mounts, emits `start-replay(cycleId)` or `close` → `App.vue` handles.

**Alternative (simpler):** `ControlBar` directly calls `fetch('/api/replay/start/...')` when "Start Replay" is clicked in the modal. The backend response + WebSocket phase update drives the ControlBar switch. `App.vue` only manages `showCyclePicker`. This matches the existing pattern where `ControlBar` owns REST calls.

### Pattern 5: Force Graph — Zero Changes Required (verified from ForceGraph.vue)

**What:** ForceGraph.vue has a `watch(() => snapshot.value.agent_states, ...)` that updates node colors directly. When replay transitions rounds, the WebSocket delivers new `agent_states` → colors update automatically.

**Edge clearing for replay start (verified from ForceGraph.vue lines 185-190):**
```typescript
watch(() => snapshot.value.phase, (newPhase) => {
  if (newPhase === 'idle' || newPhase === 'seeding') {
    edges.value = []
    triggerRef(edges)
  }
})
```
The UI-SPEC (line 217) specifies edges should clear on `phase === 'replay'` start. The existing watcher does NOT clear on `'replay'`. This watcher must add `|| newPhase === 'replay'` to clear edges when replay begins. This is the only ForceGraph change needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Round-transition data loading | Custom Cypher queries | `graph_manager.read_full_cycle_signals()` | Already implemented, performance-instrumented, returns exact `dict[tuple[str,int], AgentState]` for `ReplayStore.__init__` |
| Bracket summaries per round | Custom aggregation | `graph_manager.read_bracket_narratives_for_round(cycle_id, round_num)` | Already implemented with correct lowercase signal casing |
| Rationale entries per round | Custom query | `graph_manager.read_rationale_entries_for_round(cycle_id, round_num)` | Already implemented |
| Cycle listing query | Custom Neo4j read | `graph_manager.read_completed_cycles()` | Already powering the live `/api/replay/cycles` endpoint |
| WebSocket broadcast | Custom push mechanism | `connection_manager.broadcast(serialized_json)` | Existing non-blocking broadcast with per-client bounded queues |
| Replay data store | Custom round-slicing dict | `ReplayStore` from `state.py:246` | Already handles `set_round()`, `set_bracket_summaries()`, `set_rationale_entries()`, `snapshot()` |
| Vue modal animation | Custom CSS animation | `<Transition name="modal">` + existing drawer timing tokens | `--duration-drawer-enter: 200ms` and `--duration-drawer-exit: 150ms` already defined |

**Key insight:** This phase is ~80% wiring and ~20% new code. The data layer, broadcast infrastructure, and graph rendering are fully built.

---

## Common Pitfalls

### Pitfall 1: `isActive` Captures `replay` Phase
**What goes wrong:** `isActive` is `phase !== 'idle' && phase !== 'complete'`. When replay starts, `phase === 'replay'` makes `isActive = true`, rendering the Stop/Shock buttons alongside the replay strip.
**Why it happens:** `'replay'` was not a known phase when `isActive` was written.
**How to avoid:** Update `isActive` to exclude `'replay'` before adding the `isReplay` computed.
**Warning signs:** Seeing "Stop" and "+Inject Shock" buttons visible during replay mode.

### Pitfall 2: Broadcaster Sends Stale IDLE/COMPLETE State Between Round Advances
**What goes wrong:** If the broadcaster is not made `replay_manager`-aware, it reads `state_store.snapshot()` which returns `agent_states = {}` during replay (since no real simulation updated StateStore). The frontend receives empty agent states on every 200ms tick and clears the graph.
**Why it happens:** `StateStore` is never written to during replay — only `ReplayStore` holds round data.
**How to avoid:** Update `broadcaster.py` (or `snapshot_to_json`) to check `replay_manager.is_active` and use `replay_store.snapshot()` when true.
**Warning signs:** Force graph nodes flashing to `PENDING_COLOR` between round advances.

### Pitfall 3: ForceGraph Edges Not Cleared on Replay Start
**What goes wrong:** Edges from a prior simulation or prior replay cycle persist visually when a new replay starts.
**Why it happens:** The existing phase watcher only clears edges on `'idle'` and `'seeding'`, not `'replay'`.
**How to avoid:** Add `|| newPhase === 'replay'` to the ForceGraph phase watcher.
**Warning signs:** Old influence edges from previous cycle visible during replay Round 1.

### Pitfall 4: ReplayStore Signal Types vs Frontend String Comparison
**What goes wrong:** `ReplayStore.snapshot()` returns `AgentState(signal=SignalType.BUY, ...)`. The Python JSON serializer will emit `"signal": "buy"` since `SignalType` is a string enum. This matches the frontend `SIGNAL_COLORS` map keys (`'buy'`, `'sell'`, `'hold'`). However, if `SignalType` is ever serialized differently (e.g., `"BUY"` uppercase), `SIGNAL_COLORS[signal]` will miss and nodes stay `PENDING_COLOR`.
**Why it happens:** Python `dataclasses.asdict()` does not transform enum values — they serialize as their `.value`. `SignalType` values are lowercase strings (`'buy'`, `'sell'`, `'hold'`).
**How to avoid:** Verify with an existing simulation replay that `ReplayStore.snapshot()` serializes correctly before testing in browser.
**Warning signs:** All replay nodes showing as gray `#374151` regardless of actual signal.

### Pitfall 5: `replay_start` Called Concurrently (No Guard)
**What goes wrong:** Two rapid clicks on "Start Replay" trigger two concurrent calls to `POST /api/replay/start/{cycle_id}`. Both calls call `read_full_cycle_signals` and race to set `replay_manager._store`.
**Why it happens:** No lock guard on `ReplayManager.start()` (unlike `SimulationManager` which uses `asyncio.Lock`).
**How to avoid:** Add `asyncio.Lock` to `ReplayManager` and check `is_active` before starting. Return 409 if already active.
**Warning signs:** Race condition in Neo4j — two simultaneous reads followed by inconsistent store state.

### Pitfall 6: CyclePicker Fetches on Mount But Not on Re-Open
**What goes wrong:** `GET /api/replay/cycles` is fetched on `onMounted` in `CyclePicker.vue`. User opens picker, sees list, closes it, runs a new simulation, opens picker again — but sees the stale cached list.
**Why it happens:** Fetching only on mount means closing and re-mounting the modal does re-fetch (because `v-if` destroys and recreates the component). This is actually fine with the `v-if` mounting pattern.
**How to avoid:** Since `CyclePicker.vue` is mounted via `v-if="showCyclePicker"` in `App.vue`, each open creates a fresh component instance and triggers `onMounted` → fresh fetch. No caching issue. Confirm the component is destroyed on close (not hidden with `v-show`).
**Warning signs:** Stale cycle list — would only happen if `v-show` is mistakenly used instead of `v-if`.

### Pitfall 7: `read_full_cycle_signals` Returns Empty for In-Progress Cycles
**What goes wrong:** User selects a cycle that has Round 1 and Round 2 data but no Round 3 — `replay_start` loads signals but `ReplayStore.set_round(1)` shows only 100 entries, no bracket summaries for Round 3.
**Why it happens:** `read_completed_cycles()` filters to cycles with Round 3 decisions (verified from `graph.py:1870-1877`). This is correct behavior — all cycles shown in the picker are complete. Not actually a pitfall, but worth confirming in tests.
**How to avoid:** The `replay_cycles` endpoint already uses `read_completed_cycles()` which only returns complete cycles. Trust this invariant.

---

## Code Examples

### ReplayManager Skeleton (verified from SimulationManager pattern)

```python
# Source: src/alphaswarm/web/simulation_manager.py (structural mirror)
import asyncio
import dataclasses
import json
from alphaswarm.state import ReplayStore, RationaleEntry, BracketSummary

class ReplayAlreadyActiveError(Exception):
    pass

class NoReplayActiveError(Exception):
    pass

class ReplayManager:
    def __init__(self, app_state: "AppState") -> None:
        self._app_state = app_state
        self._lock = asyncio.Lock()
        self._store: ReplayStore | None = None
        self._cycle_id: str | None = None
        self._round_num: int = 0

    @property
    def is_active(self) -> bool:
        return self._store is not None

    @property
    def store(self) -> ReplayStore:
        if self._store is None:
            raise NoReplayActiveError("No replay active")
        return self._store

    @property
    def round_num(self) -> int:
        return self._round_num
```

### replay_start Implementation Sketch (verified from replay.py stubs + CONTEXT.md D-08)

```python
# Source: src/alphaswarm/web/routes/replay.py — filling in the stub
@router.post("/replay/start/{cycle_id}", response_model=ReplayStartResponse)
async def replay_start(cycle_id: str, request: Request) -> ReplayStartResponse:
    app_state = request.app.state.app_state
    replay_manager = request.app.state.replay_manager
    connection_manager = request.app.state.connection_manager
    graph_manager = app_state.graph_manager
    if graph_manager is None:
        raise HTTPException(status_code=503, detail={"error": "graph_unavailable", ...})
    if replay_manager.is_active:
        raise HTTPException(status_code=409, detail={"error": "replay_already_active", ...})
    try:
        signals = await graph_manager.read_full_cycle_signals(cycle_id)
    except Exception:
        raise HTTPException(status_code=404, detail={"error": "cycle_not_found", ...})
    if not signals:
        raise HTTPException(status_code=404, detail={"error": "cycle_not_found", ...})
    await replay_manager.start(cycle_id, signals, connection_manager)
    return ReplayStartResponse(status="ok", cycle_id=cycle_id, round_num=1)
```

### ControlBar isReplay Fix (verified from ControlBar.vue lines 9-11)

```typescript
// Source: frontend/src/components/ControlBar.vue
// BEFORE (current):
const isActive = computed(() =>
  snapshot.value.phase !== 'idle' && snapshot.value.phase !== 'complete'
)

// AFTER (Phase 34):
const isActive = computed(() =>
  snapshot.value.phase !== 'idle' &&
  snapshot.value.phase !== 'complete' &&
  snapshot.value.phase !== 'replay'      // <-- critical addition
)
const isReplay = computed(() => snapshot.value.phase === 'replay')
```

### ForceGraph Edge Clear Fix (verified from ForceGraph.vue lines 185-190)

```typescript
// Source: frontend/src/components/ForceGraph.vue
// BEFORE:
watch(() => snapshot.value.phase, (newPhase) => {
  if (newPhase === 'idle' || newPhase === 'seeding') {
    edges.value = []
    triggerRef(edges)
  }
})

// AFTER (Phase 34):
watch(() => snapshot.value.phase, (newPhase) => {
  if (newPhase === 'idle' || newPhase === 'seeding' || newPhase === 'replay') {
    edges.value = []
    triggerRef(edges)
  }
})
```

### Broadcaster Update (D-11 pattern)

```python
# Source: src/alphaswarm/web/broadcaster.py — updated to accept replay_manager
def snapshot_to_json(state_store: StateStore, replay_manager=None) -> str:
    if replay_manager is not None and replay_manager.is_active:
        snap = replay_manager.store.snapshot()
        d = dataclasses.asdict(snap)
        # ReplayStore.snapshot() already sets rationale_entries from set_rationale_entries()
        return json.dumps(d)
    snap = state_store.snapshot()
    rationales = state_store.drain_rationales(5)
    d = dataclasses.asdict(snap)
    d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]
    return json.dumps(d)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate polling endpoint for replay | WebSocket broadcast reuse (same tick, same path) | Decision D-11 (Phase 34 design) | No new polling loop; replay snapshots arrive at 200ms interval identical to live simulation |
| Frontend owns cycle list state | Fetch-on-open in CyclePicker | Decision D-02 (Phase 34 design) | Idle app state stays lightweight; no eager fetch |
| Replay as separate route/view | Mode flag (`phase === 'replay'`) on shared views | Decision D-03 (Phase 34 design) | ForceGraph, AgentSidebar, RationaleFeed, BracketPanel work unchanged in replay |

---

## Open Questions

1. **Broadcaster refactor scope**
   - What we know: `start_broadcaster()` in `broadcaster.py` takes `(state_store, connection_manager)`. `replay_manager` is created in `lifespan` after `start_broadcaster` is called.
   - What's unclear: Whether to pass `replay_manager` as a parameter to `start_broadcaster` or access it via `app_state` (which `connection_manager` does not have access to).
   - Recommendation: Pass `replay_manager` as a third parameter to `start_broadcaster`. Since it is created in lifespan before the broadcaster task starts, the reference is valid. This is the cleanest approach.

2. **`read_full_cycle_signals` performance under load**
   - What we know: STATE.md blocker notes: "Phase 28 (Replay): read_full_cycle() Cypher query needs performance profiling for COLLECT aggregation across 600+ nodes." The Phase 28 implementation uses flat rows (`ORDER BY d.round, a.id`) not COLLECT — this optimization was already applied (see `graph.py:1786`: "Uses flat rows (not COLLECT) for optimal index usage").
   - What's unclear: Actual measured latency on production Neo4j with 600+ nodes.
   - Recommendation: The plan should include a verification step: time `read_full_cycle_signals` on a real completed cycle. Add a loading state in the CyclePicker ("Starting...") per the UI-SPEC to handle up to 2 seconds gracefully.

3. **`replay_stop` phase transition on StateStore**
   - What we know: `SimulationManager._on_task_done` resets `state_store.phase` to IDLE on cancel/failure. `replay_stop` must do the same.
   - What's unclear: Whether resetting `state_store.phase` to IDLE is sufficient or if additional cleanup (clearing `state_store._agent_states`) is needed.
   - Recommendation: Call `await state_store.set_phase(SimulationPhase.IDLE)` in `ReplayManager.stop()`. The broadcaster will then resume sending IDLE snapshots. ForceGraph node states persist until a new simulation starts (consistent with existing behavior per UI-SPEC).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|---------|
| Python | FastAPI/ReplayManager | Yes | 3.10.14 | — |
| uv | Package management | Yes | 0.11.0 | — |
| Node.js | Vite/Vue build | Yes | v23.6.0 | — |
| uvicorn | FastAPI server | Yes | (in miniforge3) | — |
| Neo4j | read_full_cycle_signals | Not checked (external service) | — | Tests run without Neo4j; graph_manager = None returns 503 |
| pytest-asyncio | Existing test suite | Yes (asyncio_mode=auto in pyproject.toml) | — | — |

**Missing dependencies with no fallback:** None (all code paths have 503 fallbacks when Neo4j is unavailable).

**Note:** All new tests should follow the established `_make_test_app()` pattern with `with_neo4j=False` for unit coverage, plus manual human verification with live Neo4j for integration.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_web.py -x` |
| Full suite command | `uv run pytest tests/test_web.py -v` |
| Test file | `tests/test_web.py` (existing — 32 tests collected) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WEB-06 / REPLAY-01 | `POST /api/replay/start/{cycle_id}` with real logic returns `round_num=1` and triggers WebSocket broadcast | unit (mock graph_manager) | `uv run pytest tests/test_web.py -k "replay_start" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | `POST /api/replay/advance` increments round, returns new `round_num` | unit (mock replay_manager) | `uv run pytest tests/test_web.py -k "replay_advance" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | `POST /api/replay/stop` resets phase to IDLE | unit | `uv run pytest tests/test_web.py -k "replay_stop" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | `POST /api/replay/start` returns 409 when replay already active | unit | `uv run pytest tests/test_web.py -k "replay_already_active" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | `POST /api/replay/start` returns 404 when cycle not found | unit (mock graph_manager raises) | `uv run pytest tests/test_web.py -k "cycle_not_found" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | `POST /api/replay/stop` route registered in production app | unit | `uv run pytest tests/test_web.py -k "replay_routes" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | broadcaster uses replay_store.snapshot() when replay is active | unit | `uv run pytest tests/test_web.py -k "broadcaster_replay" -x` | Wave 0 gap |
| WEB-06 / REPLAY-01 | Force graph clears edges on `phase === 'replay'` — MANUAL only | manual | Human verification in browser | N/A |
| WEB-06 / REPLAY-01 | ControlBar shows replay strip when `phase === 'replay'` — MANUAL only | manual | Human verification in browser | N/A |
| WEB-06 / REPLAY-01 | CyclePicker modal opens, lists cycles, starts replay — MANUAL only | manual | Human verification in browser | N/A |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_web.py -x`
- **Per wave merge:** `uv run pytest tests/test_web.py -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] Add `test_replay_start_real_logic` — covers `ReplayManager.start()` with mocked `graph_manager.read_full_cycle_signals`
- [ ] Add `test_replay_advance_real_logic` — covers round increment, `ReplayStore.set_round()`, and broadcast call
- [ ] Add `test_replay_stop_resets_phase` — mirrors `test_sim_manager_cancellation_resets_phase_to_idle`
- [ ] Add `test_replay_start_409_already_active` — concurrency guard
- [ ] Add `test_replay_start_404_cycle_not_found` — empty signals dict → 404
- [ ] Add `test_replay_stop_route_registered` — production app route presence check
- [ ] Add `test_broadcaster_uses_replay_snapshot_when_active` — confirms broadcaster switches to `replay_manager.store.snapshot()` when `is_active`
- [ ] Update `_make_test_app` to include `app.state.replay_manager` (currently missing — will cause `AttributeError` in new endpoint handlers)

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 34 |
|-----------|-------------------|
| 100% async (`asyncio`) | `ReplayManager` methods (`start`, `advance`, `stop`) must all be `async`. Any Neo4j calls inside are already async. |
| No blocking I/O on main event loop | `read_full_cycle_signals` is already `async` via `neo4j` async driver. No sync reads. |
| Local First — no cloud APIs | No new external services introduced. All data from local Neo4j. |
| Memory Safety — monitor RAM | `ReplayStore` holds 300 `AgentState` objects (100 agents × 3 rounds). Memory footprint is negligible (~50KB). No pressure concern. |
| `uv` as package manager | All new packages installed via `uv add`. Phase 34 adds no new packages. |
| Python 3.11+ strict typing | `ReplayManager` must use `from __future__ import annotations` and full type annotations. |
| `pydantic`, `pydantic-settings` | New request/response models (`ReplayStopResponse`) must use `pydantic.BaseModel`. |
| `structlog` | `ReplayManager` and new endpoints must use `structlog.get_logger(component="web.replay_manager")`. |
| GSD Workflow Enforcement | All file changes through GSD execute-phase. No direct edits. |

---

## Sources

### Primary (HIGH confidence — code read directly from repository)

- `src/alphaswarm/web/routes/replay.py` — exact stub signatures, response schemas, existing `replay_cycles` live implementation
- `src/alphaswarm/state.py:246-294` — `ReplayStore` full implementation: `set_round()`, `set_bracket_summaries()`, `set_rationale_entries()`, `snapshot()`
- `src/alphaswarm/graph.py:1782-1937` — `read_full_cycle_signals()`, `read_completed_cycles()`, `read_bracket_narratives_for_round()`, `read_rationale_entries_for_round()` — all fully implemented
- `src/alphaswarm/web/simulation_manager.py` — `SimulationManager` pattern for `ReplayManager` to mirror
- `src/alphaswarm/web/connection_manager.py` — `broadcast()` API: synchronous, non-blocking, drop-oldest
- `src/alphaswarm/web/broadcaster.py` — `snapshot_to_json()` and `_broadcast_loop()` — confirmed reads from `StateStore` only; must be extended
- `src/alphaswarm/web/app.py` — lifespan pattern, `app.state` mounting pattern
- `src/alphaswarm/app.py` — `AppState` dataclass — confirmed `replay_manager` field does not yet exist
- `frontend/src/components/ControlBar.vue` — `isActive` computed (lines 9-11), `phaseLabel` map (line 44 — `'replay': 'Replay'` already there), button patterns
- `frontend/src/components/ForceGraph.vue` — color-watch (lines 127-148), edge-clear watcher (lines 185-190), node-click emit (line 213)
- `frontend/src/App.vue` — `provide('snapshot')`, `selectedAgentId` wiring, `isIdle` computed, Transition/AgentSidebar mount pattern
- `frontend/src/types.ts` — `StateSnapshot.phase` union includes `'replay'`; `AgentState`, `SIGNAL_COLORS` verified
- `frontend/src/composables/useWebSocket.js` — WebSocket reconnect, snapshot update, `allRationales` reset on `'idle'` phase
- `frontend/src/assets/variables.css` — all existing tokens confirmed; 4 new tokens needed
- `frontend/src/components/ShockDrawer.vue` — ghost button style reference for Close Picker and Replay idle button
- `tests/test_web.py` — 32 tests collected; `_make_test_app()` pattern; existing `test_replay_start_stub` / `test_replay_advance_stub` will need updating
- `.planning/config.json` — `nyquist_validation: true` confirmed

### Secondary (MEDIUM confidence)

- `34-CONTEXT.md` — all 11 decisions (D-01 through D-11) and Claude's Discretion areas
- `34-UI-SPEC.md` — exact CSS specifications, copy contract, animation tokens, component anatomy

### Tertiary (LOW confidence)

- None — all critical claims verified from direct code reads.

---

## Metadata

**Confidence breakdown:**

- Backend architecture (ReplayManager, broadcaster coupling): HIGH — code read directly; patterns verified from SimulationManager
- Frontend component changes (ControlBar, ForceGraph, App.vue): HIGH — code read directly; change surface is small and well-defined
- Pitfall identification: HIGH — derived from reading actual implementation, not assumed
- Test gaps: HIGH — compared existing test list against new endpoint surface

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable codebase; no fast-moving dependencies)
