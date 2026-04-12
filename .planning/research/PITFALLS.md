# Pitfalls Research: v5.0 Web UI

**Domain:** Adding Vue 3 + FastAPI WebSocket UI with live force-directed graph to existing Python asyncio multi-agent simulation engine (M1 Max 64GB, Ollama, Neo4j)
**Researched:** 2026-04-12
**Confidence:** HIGH (verified against existing codebase architecture + ecosystem research from FastAPI/D3/Vue 3 documentation and community sources)

---

## Critical Pitfalls

Mistakes that cause architectural rewrites, deadlocks, memory leaks, or degraded simulation fidelity when adding the web layer.

---

### Pitfall 1: Event Loop Conflict -- Uvicorn Creates Its Own Loop, Simulation Expects to Own It

**What goes wrong:**
The existing simulation runs via `asyncio.run()` in the CLI entrypoint. Uvicorn also calls `asyncio.run()` internally when started with `uvicorn.run()`. Two calls to `asyncio.run()` cannot coexist -- the second raises `RuntimeError: This event loop is already running`, or worse, creates a separate event loop. If separate loops exist, all of AlphaSwarm's asyncio primitives (`asyncio.Queue` in StateStore/WriteBuffer, `asyncio.Lock` in StateStore, `asyncio.Event` in ResourceGovernor's `_resume_event`, the governor's `_monitor_task` created via `asyncio.create_task`) silently bind to the wrong loop. The governor's `_resume_event.wait()` never resolves because the event was created in loop A but the simulation runs in loop B. This is the exact class of bug that caused the 7-bug governor deadlock (Bugs 1-5 in the governor bug analysis).

**Why it happens:**
Both Uvicorn and the AlphaSwarm simulation were designed as top-level event loop owners. The simulation's `run_simulation()` is called from `asyncio.run(main())` in `__main__.py`. Uvicorn's `uvicorn.run()` also calls `asyncio.run()`. Two top-level owners cannot share a single process without one yielding ownership. Developers try to "just add FastAPI" without restructuring the entrypoint.

**How to avoid:**
Let Uvicorn own the event loop. Use FastAPI's `lifespan` context manager to create all asyncio objects inside Uvicorn's loop:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # All asyncio objects created HERE, inside Uvicorn's loop
    app.state.store = StateStore()
    app.state.governor = ResourceGovernor(settings, state_store=app.state.store)
    yield
    await app.state.governor.stop_monitoring()

app = FastAPI(lifespan=lifespan)
```

The simulation is started as a task (`asyncio.create_task(run_simulation(...))`) from a WebSocket endpoint or REST trigger, not from the process entrypoint. This guarantees one loop, one owner.

Alternative: embed Uvicorn via `uvicorn.Config` + `uvicorn.Server` and `await server.serve()` inside an `async def main()`. Either way: Uvicorn must be the loop owner.

**Warning signs:**
- `RuntimeError: This event loop is already running` at startup
- Governor `_resume_event.wait()` hangs forever (Event from wrong loop)
- `asyncio.Queue` operations silently deadlock (Queue from wrong loop)
- Tests pass (single loop) but production fails (two loops attempted)
- `asyncio.get_running_loop()` returns different objects in simulation vs WebSocket handler

**Phase to address:**
Phase 1 (FastAPI skeleton) -- this is the foundational decision. Every other feature depends on a shared event loop.

---

### Pitfall 2: StateStore.snapshot() Drain Semantics Break Multi-Consumer WebSocket Broadcast

**What goes wrong:**
`StateStore.snapshot()` has a **destructive side effect**: it drains up to 5 entries from `_rationale_queue` per call (state.py lines 200-204). This was designed for a single TUI consumer polling at 200ms. With WebSocket broadcast, if `snapshot()` is called once per tick and broadcast to N clients, it appears to work. But if any code path calls `snapshot()` more than once per tick -- a REST endpoint for current state, a health check, a second WebSocket handler, debug logging -- rationale entries are consumed by the first caller and subsequent callers get empty tuples.

The `ReplayStore` already demonstrates the correct pattern: its `snapshot()` is explicitly non-destructive (state.py lines 259-280, documented: "No side effects -- calling snapshot() twice returns identical data").

**Why it happens:**
Single-consumer drain is a valid pattern for 1:1 producer-consumer (TUI). WebSocket broadcast is 1:N. The drain-on-read semantic silently violates the broadcast contract. The existing code comment documents this: "Side effect: drains up to 5 rationale entries from the queue per call. This is intentional -- the TUI consumes entries in batches of 5 per 200ms tick."

**How to avoid:**
Refactor `StateStore.snapshot()` to be non-destructive, following `ReplayStore`'s pattern:

1. Move rationale draining to a separate `drain_rationales() -> tuple[RationaleEntry, ...]` method.
2. A single broadcaster task calls `drain_rationales()` once per tick, stores the result, then calls `snapshot()` (now side-effect-free).
3. The broadcast payload combines the snapshot with the drained rationales.
4. All clients receive the same payload from the same single drain.

Alternatively, replace the rationale queue with a ring buffer that `snapshot()` reads via a cursor, similar to how `_bracket_summaries` works (set once, read many times).

**Warning signs:**
- Rationale sidebar works in one browser tab but is empty in a second tab opened simultaneously
- Rationale entries appear intermittently or "split" across clients
- REST endpoint for current state returns different rationale data than WebSocket stream
- Unit test passes (single consumer) but integration test with two WebSocket clients fails

**Phase to address:**
Phase 1-2 (StateStore refactor) -- must be resolved before WebSocket broadcast is implemented.

---

### Pitfall 3: WebSocket send_json() Blocks the Event Loop When a Client Is Slow

**What goes wrong:**
`await websocket.send_json(payload)` is a coroutine that blocks until data is written to the client's TCP buffer. If a client is on a slow connection, has a debugger breakpoint, or has a frozen browser tab, `send_json()` blocks. In a naive broadcast loop that awaits `send_json()` sequentially for each client, one slow client stalls the entire broadcast. Since the broadcast runs on the same event loop as the simulation's governor monitor, WriteBuffer flush, and agent dispatch, the entire simulation freezes for the duration of the slow send.

Starlette's WebSocket API provides no built-in backpressure detection. There is no `getBufferedAmount()` equivalent. `websocket.client_state` continues to report `WebSocketState.CONNECTED` even after the client is effectively dead (confirmed in FastAPI Discussion #9031 and Starlette Issue #1811).

**Why it happens:**
Developers assume `await send_json()` is "instant" because it usually is on localhost. But even on localhost, a paused browser tab (user switches apps on macOS) can slow TCP consumption. The coroutine awaits the ASGI send, which awaits the TCP write, which awaits the client to drain its receive buffer. One stalled client creates a cascade: broadcast stalls, governor monitor misses its check interval, governor enters CRISIS from a missed reading, simulation hangs.

**How to avoid:**
Per-client queue architecture, isolating slow clients from the broadcast path:

1. Each connected client gets a bounded `asyncio.Queue(maxsize=10)`.
2. The broadcast tick serializes the snapshot once, then calls `queue.put_nowait()` for each client. On `QueueFull`, drop the oldest message (same pattern as StateStore's rationale queue, lines 155-162).
3. Each client has a dedicated writer task that reads from its queue and sends with a timeout: `asyncio.wait_for(ws.send_json(msg), timeout=5.0)`.
4. On timeout or `WebSocketDisconnect`, the writer task tears down and removes the client from the connection manager.

This isolates slow clients: their queue fills, messages are dropped, and eventually they're disconnected -- but the simulation never blocks.

**Warning signs:**
- Simulation TPS drops when a second browser tab is opened
- Governor `_monitor_loop` misses check intervals during broadcast (visible in structlog)
- Opening browser DevTools (which pauses JS execution) freezes the simulation
- `asyncio.get_event_loop().time()` drift spikes during broadcast ticks

**Phase to address:**
Phase 2 (WebSocket server) -- per-client queue must be in place from the first broadcast endpoint.

---

### Pitfall 4: Ollama LLM Calls Block WebSocket Serving During Agent Interviews

**What goes wrong:**
Agent interviews trigger `InterviewEngine.ask()` which calls `OllamaClient.chat()` -- a network-async but computationally slow operation (5-60 seconds depending on model and context size). On M1 Max with `OLLAMA_MAX_LOADED_MODELS=2`, the worker model (`qwen3.5:7b`) serves both simulation agents and interviews. Ollama serializes requests per model by default (without `--parallel`). If an interview is triggered during an active simulation, the interview request queues behind up to 16 concurrent agent inference calls. The interview response takes minutes instead of seconds.

Even with `OLLAMA_NUM_PARALLEL=16`, an interview during simulation means 17 concurrent requests competing for the same model's KV cache slots. The governor's `TokenPool` manages simulation concurrency but does not account for interview requests (by design -- `InterviewEngine` bypasses the governor per D-13). This creates an unmonitored memory pressure spike.

**Why it happens:**
The TUI design gated interviews to post-simulation only (the interview screen is only accessible after `SimulationPhase.COMPLETE`). The web UI breaks this assumption: nothing prevents a user from clicking "Interview Agent" while the simulation is running. The interview endpoint will happily call `ollama_client.chat()` during an active simulation, creating resource contention invisible to the governor.

**How to avoid:**
1. **Gate interviews to post-simulation only** (simplest, safest): The interview endpoint checks simulation phase and returns HTTP 409 if the simulation is still running. The frontend disables the interview button until `SimulationPhase.COMPLETE`. This preserves the existing design contract.
2. If mid-simulation interviews are required: create a separate `interview_semaphore = asyncio.Semaphore(1)` (cap at 1 concurrent interview). The interview endpoint acquires this semaphore, checks `governor.state` (reject if THROTTLED/PAUSED/CRISIS), then proceeds.
3. **Never** run an LLM call inside the broadcast path or any coroutine that the broadcast tick depends on. The interview must be a completely independent async lifecycle.
4. Stream interview tokens to the client as they arrive from Ollama (using `stream=True` in `ollama_client.chat()`). This gives the user immediate feedback instead of a 30-second wait with no progress.

**Warning signs:**
- Interview panel shows "loading" for 60+ seconds during an active simulation
- Governor enters CRISIS when an interview triggers mid-simulation (memory spike from extra KV cache)
- Simulation TPS drops to 0 during interview (Ollama queue contention)
- Memory pressure rises unexpectedly post-simulation (interview context window growing without governor awareness)

**Phase to address:**
Phase 1 (architecture decision: when are interviews allowed?) and Phase 4-5 (interview panel implementation with gating logic).

---

### Pitfall 5: Force-Directed Graph Layout Thrashing on Live 200ms Data Updates

**What goes wrong:**
D3's `d3.forceSimulation` computes node positions iteratively, decaying `alpha` (energy) from 1.0 toward 0 over ~300 ticks until equilibrium. When new data arrives (agent signals change, INFLUENCED_BY edges update), naive implementations call `simulation.alpha(1).restart()` to "wake up" the stopped simulation. At 200ms broadcast cadence (5 updates/second), this resets alpha to 1.0 five times per second. The graph never reaches equilibrium -- all 100 nodes perpetually bounce, edges stretch and snap, and the user cannot visually track any individual agent. The "mirofish" hero feature becomes an unusable animated blur.

**Why it happens:**
The D3 documentation says to call `simulation.alpha(1).restart()` to reheat after modifying nodes. Developers apply this on every data update because the docs describe a static dataset where you modify data once and watch it settle. With a 200ms live stream, "once" becomes "5 times per second" and the advice becomes destructive.

**How to avoid:**
1. **Separate data updates from layout updates**: When agent signals change (color, confidence opacity), update the visual attributes directly on SVG/Canvas elements WITHOUT touching the force simulation. Only reheat when the topology changes (new or removed INFLUENCED_BY edges).
2. **Warm restart, not hot restart**: For topology changes, use `simulation.alpha(0.05).alphaTarget(0.01).restart()` -- minimal energy, fast cooldown. Never `alpha(1)`.
3. **Preserve node positions on data merge**: Maintain a `Map<agentId, {x, y, vx, vy}>`. When new data arrives, merge new properties (signal, confidence) into existing position data. Never recreate the nodes array from scratch.
4. **Pin nodes after initial layout**: Once the initial layout settles (alpha reaches `alphaMin`), set `fx = x` and `fy = y` on all nodes. Subsequent signal changes only update visual properties. Unpin only when the user drags a node or when topology actually changes.
5. **Tune `alphaDecay`**: Set `alphaDecay(0.05)` (faster cooldown than the 0.0228 default) so brief reheats settle within 1-2 seconds.

**Warning signs:**
- Graph "explodes" or "bounces" on every 200ms tick
- Users report motion sickness or inability to find specific agents
- CPU usage in browser stays at 50%+ even with 100 nodes
- D3 simulation's `alpha()` never drops below 0.5 (perpetual reheat)

**Phase to address:**
Phase 3 (force-directed graph) -- alpha management and the "data update vs layout update" separation must be designed from the first implementation.

---

### Pitfall 6: D3 Force Simulation Memory Leak on Vue 3 Component Unmount

**What goes wrong:**
D3's `d3.forceSimulation` uses `d3.timer` internally, backed by `requestAnimationFrame`. If the Vue component hosting the graph is unmounted (route navigation, panel toggle, HMR during development) without explicitly calling `simulation.stop()`, the timer continues firing in the background. Each tick callback holds a closure over the nodes and edges arrays. Over repeated mount/unmount cycles -- frequent during development with HMR -- leaked simulations accumulate. On M1 Max, the browser tab grows by ~50MB per leaked instance, reaching 1GB+ after 20 HMR reloads.

Additionally, D3 zoom and drag behaviors attach event listeners to the SVG/Canvas element. If the element is removed from the DOM without removing these listeners, they hold references to the detached DOM node, preventing garbage collection.

**Why it happens:**
Vue 3's reactivity system and component lifecycle do not automatically clean up imperative D3 code. Developers set up the simulation in `onMounted()` but forget or incorrectly implement `onBeforeUnmount()` cleanup. HMR makes this worse: every file save creates a new component instance without fully unmounting the old one, and leaked timers are invisible unless you check the Performance profiler.

**How to avoid:**
Strict cleanup protocol in the graph component:

```javascript
let simulation = null;
let animationFrameId = null;

onMounted(() => {
  simulation = d3.forceSimulation(nodes)
    .force('charge', d3.forceManyBody().strength(-200))
    .on('tick', ticked);
});

onBeforeUnmount(() => {
  if (simulation) {
    simulation.stop();           // Stop d3.timer
    simulation.on('tick', null); // Remove tick listener
    simulation.nodes([]);        // Release node array reference
    simulation = null;
  }
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
  // Remove D3 event listeners
  d3.select(svgRef.value).on('.zoom', null);
  d3.select(svgRef.value).on('.drag', null);
});
```

**Warning signs:**
- Browser memory grows 50MB+ each time you navigate away from graph and back
- Multiple `d3.timer` callbacks visible in Performance profiler "Timers" section
- CPU stays at 10-20% even when graph tab is not visible
- Vue devtools shows "ghost" component instances that should have been destroyed

**Phase to address:**
Phase 3 (force-directed graph) -- cleanup must be implemented at the same time as the mount. Do not defer.

---

### Pitfall 7: Vue 3 Reactive Proxy Corrupts D3 Force Simulation's Mutable Data Model

**What goes wrong:**
D3's force simulation mutates node objects in place on every tick -- it writes `x`, `y`, `vx`, `vy` directly to each node. If the node array is stored in a Vue 3 `ref()` or `reactive()`, Vue wraps every object in an ES Proxy for change tracking. D3 then mutates the Proxy targets, triggering Vue's reactivity system on every tick. At 60fps with 100 nodes, this creates 6,000+ Proxy setter trap invocations per second, each potentially triggering watcher re-evaluations, computed recalculations, and template re-renders. Performance drops from 60fps to 10-15fps.

Worse: Vue's Proxy wrapping changes object identity. `node === rawNode` becomes false. If D3 internally compares object references (which it does in some force calculations), proxied nodes cause subtle layout bugs.

**Why it happens:**
Vue 3 uses ES Proxies by default for reactivity. `ref([...nodes])` deep-proxies the array and all nested objects. D3 was designed before frameworks used Proxies and writes directly to `node.x = newX`, triggering Vue's setter trap. This is invisible in the API -- `ref()` looks harmless.

**How to avoid:**
1. **Use `shallowRef()`** for node and edge arrays. `shallowRef` only tracks reassignment of the ref itself, not mutations to inner objects. D3 can mutate `node.x` freely without triggering Vue.
2. **Trigger updates manually** with `triggerRef(nodesRef)` after the D3 tick callback completes -- once per frame, not once per node mutation.
3. **Keep D3 data outside Vue reactivity entirely**: Store the simulation's node/edge arrays as plain JavaScript variables (not refs). Use a separate, smaller reactive object for display state updated once per frame from D3 data.
4. **D3 owns SVG rendering, Vue owns lifecycle**: Do not use `:cx="node.x"` in a Vue `v-for` template. Let D3 directly manipulate SVG attributes via `d3.select().attr()`. Vue manages when the component mounts/unmounts; D3 manages what the SVG looks like.

**Warning signs:**
- Performance profiler shows thousands of "Set" Proxy traps per frame
- Vue devtools "Timeline" shows constant component re-renders
- Graph feels sluggish despite 100 nodes being well within D3's SVG capability (~500 nodes typical)
- Adding `shallowRef()` or `markRaw()` dramatically improves performance (confirms proxy was the problem)

**Phase to address:**
Phase 3 (force-directed graph) -- the "who owns the render loop" decision must be made upfront. Recommendation: D3 owns SVG/Canvas rendering, Vue owns component lifecycle and non-graph UI.

---

### Pitfall 8: WebSocket Disconnect Detection Fails in Send-Only Broadcast Pattern

**What goes wrong:**
When a browser tab closes or the network drops, Starlette does not immediately detect the WebSocket disconnection. `websocket.client_state` continues reporting `WebSocketState.CONNECTED` after the client is gone (confirmed in Starlette Issue #1811). In a send-only broadcast pattern (server pushes state, client mostly listens), there is no `await websocket.receive_text()` call to trigger a `WebSocketDisconnect` exception. The `send_json()` call may succeed (data queued in the OS TCP buffer) or silently accumulate for minutes before the TCP keepalive timeout expires. The per-client writer task continues running, consuming event loop time and memory for a dead client.

**Why it happens:**
WebSocket disconnect detection relies on: (a) receiving a close frame, (b) a send failing at the TCP level, or (c) a ping/pong timeout. Starlette/Uvicorn does not implement automatic ping/pong. If the server only sends and never receives, there is no code path to detect disconnection until TCP itself gives up (up to 2+ minutes on macOS default keepalive).

**How to avoid:**
1. **Run a concurrent receive loop alongside the send loop**: Each client gets two tasks -- a writer (reads per-client queue, sends to WebSocket) and a reader (awaits `websocket.receive_text()` for control messages and disconnect detection). When the reader detects disconnect, it cancels the writer.
2. **Implement application-level heartbeat**: Require the client to send `{"type": "ping"}` every 15 seconds. If the server receives no message within 30 seconds, tear down the connection. VueUse's `useWebSocket` composable supports automatic heartbeat.
3. **Wrap sends in `asyncio.wait_for()`**: `asyncio.wait_for(ws.send_text(payload), timeout=5.0)` -- if the send takes more than 5 seconds, the client is effectively dead.
4. **Track connection age**: Add a `connected_at` timestamp to each client entry. Periodically scan for connections older than N minutes without any received message.

**Warning signs:**
- `len(connected_clients)` grows over time, exceeds actual open browser tabs
- Server memory slowly increases during long sessions
- Log shows "failed to send to client" errors minutes after browser was closed
- Per-client writer tasks accumulate (visible in `asyncio.all_tasks()` count)

**Phase to address:**
Phase 2 (WebSocket connection manager) -- heartbeat and dual reader/writer tasks from day one.

---

### Pitfall 9: Serialization Cost Multiplies by Client Count at 200ms Cadence

**What goes wrong:**
Starlette's `websocket.send_json(payload)` calls `json.dumps()` internally on every invocation. With N connected clients at 200ms cadence, this produces 5N JSON serializations per second. The 100-agent snapshot payload is 15-25KB of JSON. With stdlib `json.dumps()`, each serialization takes 2-5ms for complex nested dicts. At 3 clients: 15 serializations/second = 30-75ms of the 200ms budget consumed by redundant serialization alone. That is 15-37% of the event loop's time on a 200ms tick, competing with governor monitoring, WriteBuffer flushing, and agent inference dispatching.

**Why it happens:**
`send_json()` is convenient and the serialization cost is invisible. With 1 client on localhost, it is fast. The cost only surfaces when profiling or when multiple clients connect.

**How to avoid:**
1. **Serialize once, send bytes**: Call `orjson.dumps(payload).decode()` once per tick. Use `websocket.send_text(pre_serialized)` for each client. N sends, 1 serialization.
2. **Use `orjson` or `msgspec`**: 5-10x faster than stdlib `json` for this payload shape.
3. **Delta compression** (optimization, not MVP): Track what changed since last broadcast. Send only deltas. Client merges into local state. Reduces payload 90%+ during quiet periods.
4. **Adaptive cadence**: When simulation is between rounds (no agents completing), reduce broadcast to 1s. Restore 200ms during active rounds.

**Warning signs:**
- CPU profiling shows significant time in `json.dumps` during simulation
- Broadcast latency increases per additional browser tab
- Event loop latency spikes during broadcast ticks
- Network tab shows identical 25KB payloads at 200ms even when simulation is idle

**Phase to address:**
Phase 2 (WebSocket broadcast) -- serialize-once pattern from the start. Delta compression deferred to optimization.

---

### Pitfall 10: Governor suspend/resume Races with Concurrent Web Control Endpoints

**What goes wrong:**
The `ResourceGovernor` has suspend/resume semantics tied to the TUI's shock injection flow. In the web UI, shock injection becomes a REST or WebSocket endpoint. Multiple browser tabs or rapid double-clicks can send concurrent shock requests. If two requests hit the governor simultaneously, both inject their shocks, and one resume call succeeds while the simulation processes two shocks in rapid succession without handling the first. The governor's `_adjustment_lock` protects internal state transitions, but external suspend/resume has no re-entrancy guard.

Additionally, `governor.resume()` checks memory pressure and may refuse to resume if memory is above the pause threshold (this guard was added in Phase 26). The endpoint returns success but inference never resumes, and the simulation hangs forever.

**Why it happens:**
The TUI is inherently single-user: one keyboard, one modal. Web endpoints receive concurrent requests. The governor's suspend/resume contract assumed sequential, human-paced interaction.

**How to avoid:**
1. **Server-side lock**: An `asyncio.Lock` guards the shock injection flow. Second request returns HTTP 409 Conflict.
2. **Reject mutations during CRISIS/PAUSED states**: If the governor is already in CRISIS, shock injection is rejected.
3. **Frontend disables the button** while an operation is in flight. Confirm completion via WebSocket event before re-enabling.
4. **Check governor state after resume()**: If governor did not transition back to RUNNING (memory pressure too high), return a warning status. The governor's monitoring loop will eventually resume, but the user should be notified.

**Warning signs:**
- Simulation hangs after shock injection from web UI
- StateStore contains two shock entries for a single user action
- `_resume_event` stuck in cleared state after shock flow completes
- Governor monitor loop and control endpoint deadlock on `_adjustment_lock`

**Phase to address:**
Phase 4 (control panels) -- when wiring shock injection to web endpoints.

---

## Moderate Pitfalls

### Pitfall 11: Concurrent Simulation Corruption (Double Start)

**What goes wrong:** User clicks "Start Simulation" while a simulation is already running. Two `run_simulation()` tasks write to the same `StateStore`, corrupt `_agent_states` with interleaved signals from different cycles, confuse the `ResourceGovernor` (two sessions fighting over the same `TokenPool`), and produce garbage in Neo4j.

**Prevention:** `SimulationManager` with an `asyncio.Lock` guard. If `_running_task is not None and not done`, return HTTP 409. Frontend disables start button when phase is not idle/complete.

### Pitfall 12: Influence Edge Data Missing from StateSnapshot

**What goes wrong:** The Vue force graph renders nodes but no edges because `StateSnapshot` has no edge data. The TUI never displayed edges (10x10 grid), so `StateSnapshot` was designed without them. Edge data (`INFLUENCED_BY` relationships) lives only in Neo4j.

**Prevention:** Fetch edges via a separate REST endpoint (`GET /api/edges/{cycle_id}?round=N`) on round transitions. Do NOT modify StateStore to carry edge data -- it would pollute the hot-path per-agent write contract. The Vue app watches `snapshot.round_num` and fetches edges when round changes.

### Pitfall 13: Vite Dev Proxy Not Forwarding WebSocket Upgrade

**What goes wrong:** The Vue dev server proxies REST calls to FastAPI correctly, but WebSocket connections fail with 400 or hang because the proxy does not handle the HTTP Upgrade handshake.

**Prevention:** Explicitly configure WebSocket proxy in `vite.config.ts`:
```typescript
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/ws': { target: 'ws://localhost:8000', ws: true }
  }
}
```
The `ws: true` flag is required for Vite's http-proxy to handle the Upgrade handshake.

### Pitfall 14: StaticFiles Mount Order in Production FastAPI

**What goes wrong:** `app.mount("/", StaticFiles(..., html=True))` catches ALL routes including `/api/*` and `/ws/*`, returning 404 or index.html for API calls.

**Prevention:** Mount StaticFiles LAST, after all API routers are registered. FastAPI evaluates mounts in registration order. Or use a specific prefix (`/app`) for static files.

### Pitfall 15: Interview Engine Cleanup on WebSocket Disconnect

**What goes wrong:** User closes the interview panel or navigates away. The WebSocket disconnects but `InterviewEngine` (holding conversation history, Ollama session state) is never cleaned up. Over multiple interviews, memory accumulates.

**Prevention:** Use `try/finally` in the WebSocket endpoint handler. On `WebSocketDisconnect`, explicitly delete the `InterviewEngine` instance.

### Pitfall 16: orjson Serialization of Enum Values

**What goes wrong:** `orjson.dumps()` serializes Python Enum values as their string representation including the class name (`"SignalType.BUY"`) instead of the raw value (`"buy"`).

**Prevention:** Convert enums to `.value` before serialization. Build an explicit serializer function that maps `StateSnapshot` to a JSON-safe dict with `.value` on all enums.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Broadcast full 100-agent snapshot every 200ms (no deltas) | Simple implementation, no client-side merge logic | 5x bandwidth vs delta, serialization cost scales with clients | MVP / Phase 2 only; add deltas before optimization phase |
| Use `send_json()` per client (no pre-serialization) | Uses Starlette API directly, simple code | N serializations per tick | 1-2 clients only; refactor at 3+ |
| SVG rendering for 100-node graph (not Canvas) | Easy CSS styling, click events, Vue integration | Performance ceiling at ~500 nodes | Acceptable permanently -- AlphaSwarm is fixed at 100 agents |
| Polling StateStore on timer vs event-driven push | Matches existing 200ms pattern | Unnecessary ticks when state hasn't changed | MVP; add dirty-flag optimization later |
| Single `app.state` for WebSocket state (no DI) | Quick access from any endpoint | Not unit-testable, hidden coupling | Never -- use `Depends()` from the start |
| `json.dumps` instead of `orjson` | No additional dependency | 5-10x slower serialization per tick | MVP only; switch before 3+ clients |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FastAPI + asyncio simulation | Calling `uvicorn.run()` and `asyncio.run()` separately, two loops | Use `lifespan` to start asyncio objects in Uvicorn's loop |
| StateStore + WebSocket broadcast | Calling `snapshot()` per-client (drains rationale on first call) | Single broadcaster calls `snapshot()` once, serializes once, sends bytes to all |
| D3 force + Vue 3 reactivity | Storing D3 node array in `ref()` (deep Proxy triggers every tick) | `shallowRef()` + manual `triggerRef()`, or keep D3 data outside reactivity |
| Ollama interview + active simulation | `InterviewEngine.ask()` without phase check (resource contention) | Gate to post-simulation via phase check; return 409 during active simulation |
| Neo4j async driver + FastAPI | Creating Neo4j driver per-request instead of sharing pool | Create driver once in `lifespan`, pass via dependency injection |
| Vue `onBeforeUnmount` + D3 cleanup | Forgetting `simulation.stop()` and `cancelAnimationFrame()` | Explicit cleanup: stop simulation, cancel frames, remove event listeners |
| WebSocket heartbeat + send-only broadcast | Relying on `send_json()` failure to detect dead clients | Concurrent reader task per client, or require client heartbeat messages |
| Governor metrics + WebSocket telemetry | Exposing `GovernorMetrics` dataclass directly (tight coupling) | Define WebSocket-specific DTO; map internal metrics at broadcast boundary |
| StateStore change events + broadcast frequency | Setting a change event per `update_agent_state()` call (100x per round) | Throttle broadcaster to 200ms minimum interval; ignore rapid-fire events |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `json.dumps()` per-client per-tick | CPU spikes during broadcast | Serialize once with `orjson`, `send_text()` to all | 3+ clients at 200ms |
| `simulation.alpha(1).restart()` on every update | Graph never stabilizes, high browser CPU | Warm restart (alpha 0.05), separate data from layout updates | Immediately at 200ms cadence |
| Vue `ref()` proxy wrapping D3 nodes | 6000+ Proxy traps/sec, sluggish graph | `shallowRef()` + manual trigger | Immediately at 100 nodes x 60fps |
| Sequential `await send_json()` in broadcast | Slow client blocks all clients and simulation | Per-client queue + writer task with timeout | Any paused client |
| Full snapshot every 200ms when nothing changed | Wasted CPU, bandwidth, serialization | Dirty flag, skip broadcast when clean | Idle periods between rounds |
| Interview LLM during active simulation | Ollama contention, TPS drop, governor CRISIS | Gate to post-simulation or separate semaphore | Any interview during dispatch |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| WebSocket accepting arbitrary JSON without validation | Malformed data crashes simulation or corrupts StateStore | Pydantic models for all incoming WebSocket message types |
| No rate limit on interview endpoint | Spam fills Ollama queue, simulation starves | Max 1 concurrent interview, 5-second cooldown |
| Exposing governor internals to frontend | Tight coupling to implementation | Define explicit telemetry DTO |
| CORS `allow_origins=["*"]` | Any site can open WebSocket to localhost | Set `allow_origins=["http://localhost:5173"]` explicitly |
| No CSP headers for Vue static files | XSS risk via agent rationale text or seed rumor | Add `Content-Security-Policy` header; sanitize agent-generated text |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Graph re-layouts on every data update | Motion sickness, can't track agents | Warm restarts on topology change only; color updates for signals |
| No loading state for interview (30-60s) | User thinks UI broke, clicks repeatedly | Stream tokens via WebSocket, typing indicator, disable button |
| Shock injection with no feedback | User clicks, nothing happens for seconds | Immediate "Shock queued" acknowledgment, governor state in telemetry |
| 100-node graph shown all at once on load | Visual noise, overwhelming | Progressive reveal: brackets first, agents animate in, then edges |
| Bracket summaries lag behind agent signals | Stale data during active round | Compute bracket summaries client-side from broadcast payload |
| WebSocket disconnection invisible to user | Staring at stale data | Auto-reconnect with "Reconnecting..." banner; VueUse `useWebSocket` |

## "Looks Done But Isn't" Checklist

- [ ] **WebSocket broadcast:** Verify `connected_clients` count matches actual browser tabs after closing several
- [ ] **Force graph:** Verify no D3 timers running after navigating away (check Performance profiler)
- [ ] **Force graph:** Verify nodes don't jump when agent signals change (only color should change)
- [ ] **Interview panel:** Verify UX during 30s+ LLM wait (streaming tokens, not blank spinner)
- [ ] **Shock injection:** Verify two rapid clicks produce one shock, second returns error
- [ ] **StateStore:** Verify two concurrent `snapshot()` calls return identical rationale entries
- [ ] **Governor telemetry:** Verify CRISIS shows as distinct alarm state, not just another state label
- [ ] **WebSocket reconnect:** Verify frontend reconnects after FastAPI restarts and receives full state
- [ ] **Initial sync:** Verify client connecting mid-simulation receives complete current state
- [ ] **Edge animation:** Verify INFLUENCED_BY edges show directionality (arrowheads or animated flow)
- [ ] **Memory stability:** Navigate graph on/off 10 times; browser memory stays within 20MB of baseline

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Event loop conflict | HIGH | Restructure entrypoint. Move all asyncio object creation into Uvicorn lifespan. Tests need refactoring. |
| StateStore drain semantics | MEDIUM | Refactor `snapshot()` to non-destructive (follow `ReplayStore`). Add `drain_rationales()`. Update callers. |
| send_json blocks on slow client | MEDIUM | Retrofit per-client queues + writer tasks. ConnectionManager change only. |
| Graph layout thrashing | LOW | Tune alpha, add position preservation. Graph component only. |
| Vue proxy fights D3 | LOW | `ref()` to `shallowRef()`. Graph component only. |
| D3 memory leak | LOW | Add `onBeforeUnmount` cleanup. Single file change. |
| Disconnect detection | MEDIUM | Add heartbeat (server + client changes). |
| LLM blocks WebSocket | LOW (gated) | Add phase check to interview endpoint. |
| Serialization cost | LOW | `send_json` to `send_text` + `orjson`. Broadcast function only. |
| Governor race | MEDIUM | asyncio.Lock on control endpoints + CRISIS rejection. Audit all flows. |
| Concurrent simulation | LOW | SimulationManager with lock. HTTP 409. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Event loop conflict | Phase 1 (FastAPI skeleton) | `asyncio.get_running_loop()` returns same object in simulation and WebSocket handler |
| StateStore drain | Phase 1-2 (StateStore refactor) | Two concurrent `snapshot()` calls return identical rationale entries |
| WebSocket backpressure | Phase 2 (WebSocket server) | Simulation TPS unchanged with 0, 1, or 3 connected clients |
| LLM starvation | Phase 1 (arch) + Phase 4-5 (impl) | Interview during simulation returns 409 or queues correctly |
| Graph layout thrashing | Phase 3 (force graph) | Nodes stay in position when signals change (color only) |
| D3 memory leak | Phase 3 (force graph) | Navigate away/back 10x; browser memory within 20MB of baseline |
| Vue proxy vs D3 | Phase 3 (force graph) | <100 Proxy traps/frame in graph component |
| Disconnect detection | Phase 2 (connection manager) | Close tab; server logs disconnect within 15 seconds |
| Serialization pressure | Phase 2 (broadcast) | Single serialization per broadcast tick, not N |
| Governor control race | Phase 4 (control panels) | Two rapid shock clicks: one processed, second returns 409 |
| Concurrent simulation | Phase 4 (control endpoints) | Start during active sim returns 409 |
| Missing edge data | Phase 3 (force graph) | Edges render on round transition via REST fetch |
| Vite WebSocket proxy | Phase 3 (Vue SPA setup) | WebSocket connects through Vite dev proxy without errors |

## Sources

- [FastAPI WebSocket Documentation](https://fastapi.tiangolo.com/advanced/websockets/)
- [Managing WebSocket Backpressure in FastAPI](https://hexshift.medium.com/managing-websocket-backpressure-in-fastapi-applications-893c049017d4)
- [FastAPI with WebSockets at Scale: Backpressure, Fanout](https://medium.com/@hadiyolworld007/fastapi-with-websockets-at-scale-backpressure-fanout-and-the-architecture-that-doesnt-collapse-6eeb206fd991)
- [Handling WebSocket Disconnections Gracefully in FastAPI](https://hexshift.medium.com/handling-websocket-disconnections-gracefully-in-fastapi-9f0a1de365da)
- [WebSocket disconnected state not propagated -- FastAPI Discussion #9031](https://github.com/fastapi/fastapi/discussions/9031)
- [Starlette WebSocket send not raising on disconnect -- Issue #1811](https://github.com/Kludex/starlette/issues/1811)
- [Running Uvicorn from inside a running loop -- Discussion #2457](https://github.com/Kludex/uvicorn/discussions/2457)
- [ASGI Event Loop Gotcha](https://rob-blackbourn.medium.com/asgi-event-loop-gotcha-76da9715e36d)
- [D3 Force Simulation Documentation](https://d3js.org/d3-force/simulation)
- [d3-force GitHub](https://github.com/d3/d3-force)
- [How to Implement a D3.js Force-directed Graph in 2025](https://dev.to/nigelsilonero/how-to-implement-a-d3js-force-directed-graph-in-2025-5cl1)
- [Best Libraries to Render Large Force-Directed Graphs](https://weber-stephen.medium.com/the-best-libraries-and-methods-to-render-large-network-graphs-on-the-web-d122ece2f4dc)
- [VueUse useWebSocket](https://vueuse.org/core/usewebsocket/)
- [Avoiding Memory Leaks in Vue](https://v2.vuejs.org/v2/cookbook/avoiding-memory-leaks.html)
- [Vue.js Core Issue #2907 -- .unmount() memory leak](https://github.com/vuejs/core/issues/2907)
- [What Python asyncio primitives get wrong about shared state](https://www.inngest.com/blog/no-lost-updates-python-asyncio)
- [websockets Broadcasting Documentation](https://websockets.readthedocs.io/en/stable/topics/broadcast.html)
- [Ollama Concurrent Requests Configuration](https://markaicode.com/ollama-concurrent-requests-parallel-inference/)
- [FastAPI Blocking Long Running Requests -- Discussion #8842](https://github.com/fastapi/fastapi/discussions/8842)
- [Frontend Memory Leaks: 500-Repository Static Analysis Study](https://stackinsight.dev/blog/memory-leak-empirical-study/)
- [Vite Proxy Configuration](https://vite.dev/config/server-options.html#server-proxy)
- [FastAPI Static Files](https://fastapi.tiangolo.com/tutorial/static-files/)
- AlphaSwarm codebase: `src/alphaswarm/state.py` (StateStore snapshot drain, ReplayStore non-destructive pattern), `src/alphaswarm/governor.py` (TokenPool, state machine, resume_event), `src/alphaswarm/interview.py` (InterviewEngine bypasses governor per D-13), `src/alphaswarm/ollama_client.py` (async chat wrapper)
- AlphaSwarm governor deadlock bug analysis: 7 bugs across 2 sessions, rooted in event loop and asyncio primitive misuse

---
*Pitfalls research for: AlphaSwarm v5.0 Web UI -- Adding Vue 3 + FastAPI to existing asyncio simulation*
*Researched: 2026-04-12*
