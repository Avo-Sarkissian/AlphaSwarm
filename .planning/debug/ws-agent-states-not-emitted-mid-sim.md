---
status: awaiting_human_verify
trigger: "ws-agent-states-not-emitted-mid-sim — backend not emitting agent_states in WS frames during 3-round sim; advisory auto-trigger regression on cycle complete"
created: 2026-05-10
updated: 2026-05-10
---

## Current Focus

hypothesis: Fixes applied for R1 (state.py: preserve agent_states keys, reset signals to None placeholder on round entry) and R2 (batch_dispatcher.py: stream update_agent_state inside _safe_agent_inference; removed all four post-dispatch for-loops in simulation.py). Symptom-2 UX: AdvisoryV2 maxAttempts bumped 200 → 1200 (10min → 60min). Updated test_set_phase_resets_agents → test_set_phase_preserves_agent_keys_resets_signals. Added 3 new regression tests in test_batch_dispatcher.py for streaming hook (success path, PARSE_ERROR no-op, end-to-end via dispatch_wave).
test: pytest tests/test_state.py tests/test_batch_dispatcher.py tests/test_simulation.py tests/test_tui.py tests/test_web.py tests/unit/test_simulation_manager_auto_advisory.py — 225 passed, 4 deselected (pre-existing _format_peer_context format-string failures unrelated to this fix; verified by stash test). Full pytest: 911 passed (+3 vs clean master 908), 22 failed (all pre-existing, unrelated). Frontend: npm run check + npm run build both green.
expecting: User confirms in real workflow that (a) agent dots appear progressively during round dispatch, not just at round boundaries, and (b) AdvisoryV2 modal stays in polling state for the full ~60min synthesis window instead of giving up at 10min.
next_action: Wait for user verification, then archive session.

## Symptoms

expected:
  - During an active simulation, /ws frames should include agent_states[] populated with the 100 personas (id, signal/posture, edges, rationale tokens) at the broadcaster cadence (~5Hz).
  - frontend useAgents() should populate within seconds of sim start.
  - On Round-3 completion, backend should auto-fire AdvisorySynthesizer (per quick task 260507-19f) so /api/advisory returns 200, not 404.
  - Top Influencers, Rationale Feed, Bracket bars, KPI Consensus, and the force graph should all reflect live data.

actual:
  - After 65+ min of sim runtime, frontend useAgents() length is still 0.
  - Force graph renders 0 dots; Bracket bars stay green-default; Top Influencers shows "no agents yet"; Rationale Feed shows "no rationales yet"; KPI Consensus stays at "BUY 0%".
  - On cycle complete, AdvisoryV2 (frontend) opens and gets 404 from /api/advisory — backend did not auto-trigger synthesis.
  - Post-Round-3 orchestrator-load path also appears to stall/hang silently.

errors:
  - Frontend: 404 on GET /api/advisory after cycle complete.

reproduction:
  - Stack: docker `neo4j` on 7474/7687; uvicorn `alphaswarm.web.app:app --port 8000`; frontend `npm run dev`; Ollama desktop with qwen3:8b worker + qwen3.6:27b-q4_K_M orchestrator.
  - Trigger sim from UI Idle/Onboarding flow.
  - Observe /ws frames — agent_states missing/empty.
  - Wait for Round 3 → AdvisoryV2 modal opens, 404s on /api/advisory.

started:
  - Symptoms returned at start of W2 live UAT (2026-05-09/10).
  - 260507-19f (2026-05-07) wired backend auto-fire for advisory.
  - Latest commit: `7479fb6` (2026-05-10).

## Eliminated

- hypothesis: Broadcaster does not include agent_states in mid-round frames (brief's hypothesis 1).
  evidence: src/alphaswarm/web/broadcaster.py:88-96 calls `dataclasses.asdict(snap)` on the live StateSnapshot. StateSnapshot.agent_states (state.py:79) is an unconditional field of `dict[str, AgentState]`. asdict() emits it on every tick. The wire format DOES include `agent_states`. The dict is just empty most of the time. Frontend adapter at frame.ts:66-67 reads `r.agent_states ?? {}` correctly.
  timestamp: 2026-05-10

- hypothesis: Advisory auto-trigger never fires on cycle complete (brief's hypothesis 2).
  evidence: web/app.py:69 wires `on_complete=lambda cycle_id: _auto_trigger_advisory(app, cycle_id)` into SimulationManager. simulation_manager.py:207-211 calls `asyncio.create_task(self._on_complete(cycle_id), name=f"auto_advisory_{cycle_id}")` if `cycle_id is not None and self._on_complete is not None`. _auto_trigger_advisory at simulation_manager.py:32-49 does in-process httpx ASGI POST to /api/advisory/{cycle_id}. The wiring is intact.
  timestamp: 2026-05-10

- hypothesis: /api/advisory route reads from a store the auto-trigger never writes to (brief's hypothesis 3).
  evidence: Both POST handler (advisory.py:131) and synthesis worker (advisory.py:234-282) write to the SAME path: `advisory/{cycle_id}_advisory.json`. GET handler reads from that same path. No asymmetry.
  timestamp: 2026-05-10

## Evidence

- timestamp: 2026-05-10
  checked: src/alphaswarm/state.py:126-142 (set_phase)
  found: `set_phase` clears `self._agent_states.clear()` whenever phase transitions to ROUND_1, ROUND_2, or ROUND_3. Quoted code:
  ```python
  if phase in (SimulationPhase.ROUND_1, SimulationPhase.ROUND_2, SimulationPhase.ROUND_3):
      self._agent_states.clear()
  ```
  Comment says "Reset agent states to pending at each round start for clean visual slate (D-05)".
  implication: Every round entry wipes the dict to empty. This is a deliberate design intent inherited from TUI ("clean visual slate") but it directly causes the "0 dots during round" symptom because nothing writes back into the dict during the 14-18min dispatch window.

- timestamp: 2026-05-10
  checked: src/alphaswarm/simulation.py:498-541 (Round 1 dispatch)
  found: Sequence is:
    line 498: `await state_store.set_phase(SimulationPhase.ROUND_1)` ← clears dict
    line 514-524: `decisions = await dispatch_wave(...)` ← 14-18min on M1 Max
    line 538-541: per-agent for-loop calling `state_store.update_agent_state(agent_id, dec.signal, dec.confidence)` AFTER dispatch_wave returns
  Identical pattern at lines 933-999 (R2) and 1074-1133 (R3).
  implication: Per-agent state writes happen AFTER all 100 agents complete their inference. The dict is empty during the entire round dispatch window.

- timestamp: 2026-05-10
  checked: src/alphaswarm/batch_dispatcher.py:39-83 (_safe_agent_inference) + src/alphaswarm/worker.py:60-115
  found: dispatch_wave threads state_store through to AgentWorker SOLELY for TPS metric collection. worker.py:108-112 only calls `self._state_store.update_tps(eval_count, eval_duration)`. There is NO call to `update_agent_state` from anywhere inside the worker / dispatcher / inference path.
  implication: The streaming path that would populate agent_states mid-dispatch does not exist. The ONLY writer is the batch for-loop in simulation.py that runs after dispatch_wave returns.

- timestamp: 2026-05-10
  checked: src/alphaswarm/web/broadcaster.py:88-96
  found: Live snapshot path:
  ```python
  snap = state_store.snapshot()
  rationales = state_store.drain_rationales(5)
  d = dataclasses.asdict(snap)
  d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]
  ```
  No filtering, no exclusion of agent_states. Whatever is in the dict at snapshot time goes onto the wire.
  implication: Broadcaster is correct. Symptom is a producer-side problem (dict is empty), not a transport-side problem.

- timestamp: 2026-05-10
  checked: src/alphaswarm/web/simulation_manager.py:22-49 (_auto_trigger_advisory) + 191-211 (_on_task_done)
  found: After run_simulation completes, _on_task_done releases the lock and creates an auto_advisory task that calls `_auto_trigger_advisory(app, cycle_id)`. That function uses `httpx.ASGITransport(app=app)` to call POST /api/advisory/{cycle_id} in-process. POST handler then creates `_run_advisory_synthesis` task which loads the orchestrator (~17.4 GB) and synthesizes. Wiring is intact end-to-end.
  implication: The auto-trigger is firing. The user's "404 on /api/advisory" is the documented "still generating" contract (advisory.ts:21: "404 means still generating (returns null)"). What looks like "stall/hang silently" is the orchestrator load + synthesis genuinely taking several minutes.

- timestamp: 2026-05-10
  checked: src/alphaswarm/simulation.py:1198-1212 + 1251-1347 (_generate_decision_narratives)
  found: After Round 3 dispatch, the worker model is held loaded for ANOTHER 100 inferences to generate per-agent narratives via _generate_decision_narratives. asyncio.gather over 100 prompts at NUM_PARALLEL=4 ≈ 25 sequential inference batches. On M1 Max with avg ~30-60s/call, this is another ~12-25 minutes BEFORE the worker unloads, BEFORE the orchestrator loads, BEFORE advisory synthesis even starts.
  implication: Time-from-end-of-R3 to advisory file written can easily exceed 25-30 minutes on this hardware. Frontend polling cap is `maxAttempts: 200` at 3000ms = 600s = 10 min (v2.tsx:633). User likely gives up before synthesis completes. This LOOKS like "advisory never fires" but is actually "advisory is taking >10 min wall-clock from first cycle-complete poll".

- timestamp: 2026-05-10
  checked: frontend/src/hooks/useCurrentCycle.ts:8-25
  found: Frontend cycleId is derived from `/api/replay/cycles[0].cycle_id`, polled every 5s. Replay/cycles route (web/routes/replay.py:84) calls `graph_manager.read_completed_cycles()` which only returns cycles that have at least one Round 3 decision in Neo4j.
  implication: cycleId is null until R3 writes its first decision (at simulation.py:1139 `write_decisions(round3_decisions, ...)`). Until then, advisoryFetch is short-circuited to Promise.resolve(null). After R3 writes, the frontend has a cycleId and starts hitting /api/advisory/{cycle_id} — getting 404 until the orchestrator finishes synthesis.

- timestamp: 2026-05-10
  checked: frontend/src/adapter/frame.ts:120-133 (rationale adapter)
  found: Adapter correctly reads `re.rationale` and `re.round_num` (matches state.py:60 RationaleEntry wire shape).
  implication: The previous diagnosis's symptom 3 (rationale field-name mismatch) is FIXED in current HEAD. The "no rationales yet" the user sees is downstream of the root-round-state issue: rationales DO arrive correctly between rounds, but during the long round dispatch window the rationale queue is also empty because rationale entries are only pushed by `_push_top_rationales` AFTER each round dispatch completes (simulation.py:902-907, 1043-1049, 1172-1175).

- timestamp: 2026-05-10
  checked: src/alphaswarm/web/routes/advisory.py:48-141 (POST handler) vs:144-185 (GET handler)
  found: POST writes to `advisory/{cycle_id}_advisory.json` (line 264-266). GET reads same path (line 155-156). Same store. No write/read asymmetry.
  implication: Brief's hypothesis 3 is eliminated.

- timestamp: 2026-05-10
  checked: prior debug session .planning/debug/parallel-swarm-serial-dispatch.md (Phase 41.4 diagnosis)
  found: That investigation already established that wall-clock per round is hardware-bound (60-180s per inference call, NUM_PARALLEL=4, prompt size ~2.5k tokens). A "fast" full 3-round / 100-agent cycle is ~35-45 min. Plus narrative generation. Plus orchestrator load + advisory synthesis. Total cycle-to-advisory-ready is realistically ~50-70 min.
  implication: User's "65+ min, still empty" observation is consistent with the sim still being mid-round-3 OR mid-narrative-generation OR mid-orchestrator-load. Empty UI is an artifact of the agent-state-clear-on-round-entry bug — once that is fixed, the user will at least SEE round-by-round progress and the UI will stop appearing frozen.

## Resolution

root_cause:

  **TWO confirmed independent backend bugs causing symptom 1; symptom 2 is NOT a regression.**

  **(R1) `_agent_states.clear()` on every round entry wipes the dict that the broadcaster reads.**
  - File: src/alphaswarm/state.py, lines 131-136 (StateStore.set_phase).
  - Code: `if phase in (ROUND_1, ROUND_2, ROUND_3): self._agent_states.clear()`.
  - Effect: At each round entry the dict is wiped. Combined with R2 (below), the dict stays empty for the entire round duration. Broadcaster sends `agent_states: {}` on every 200ms tick during the 14-18min dispatch window.
  - Origin: TUI-era "clean visual slate" intent. Was acceptable for a TUI that updated synchronously per-agent. Wrong contract for a 5Hz WS broadcaster reading a slow-fill dict.

  **(R2) Per-agent state writes are batched AFTER `dispatch_wave` returns, not streamed during dispatch.**
  - File: src/alphaswarm/simulation.py, lines 538-541 (R1), 718-720 (R2 first branch), 998-999 (R2 dynamic branch), 1131-1133 (R3).
  - Code in each:
    ```python
    if state_store is not None:
        for agent_id, dec in agent_decisions:
            await state_store.update_agent_state(agent_id, dec.signal, dec.confidence)
    ```
  - This for-loop only runs after the entire 100-agent TaskGroup in dispatch_wave completes (~14-18 min on M1 Max with qwen3:8b q4_K_M + NUM_PARALLEL=4).
  - The worker.py inference path passes `state_store` for TPS metrics ONLY (worker.py:108-112). It never calls `update_agent_state` per-agent.
  - Effect: Even after R1 fixes the clear, the dict still does not populate until each round completes. Frontend would see 0→100 jumps at round boundaries, not progressive fills. (Combined with R1, the result is "always empty during rounds" — exactly what the user observed.)

  **Symptom 2 (advisory 404 after cycle complete) is NOT a regression.**
  - Auto-trigger is wired correctly (web/app.py:69 → simulation_manager.py:207-211 → simulation_manager.py:22-49 → POST /api/advisory/{cycle_id} → advisory.py:131 spawns _run_advisory_synthesis).
  - The 404 is the contract: file does not exist yet, no error recorded. advisory.ts:21 documents "404 means still generating (returns null)".
  - The "stall/hang silently" perception is real but is wall-clock cost, not a defect:
    - Post-R3 narrative generation: ~12-25 min (100 worker inferences via asyncio.gather, simulation.py:1196-1212).
    - Worker unload + orchestrator (~17.4 GB) load: ~30-90s on M1 Max from cold.
    - Orchestrator advisory synthesis: ~2-5 min.
    - Total: well past the AdvisoryV2 polling cap of `maxAttempts: 200 × 3000ms = 10 min` (v2.tsx:633).
  - Frontend cycleId polling adds further confusion: cycleId is null until R3's first write (useCurrentCycle.ts derives from /api/replay/cycles which graph_manager filters to "has at least one R3 decision").

  **Confidence:**
  - R1: HIGH — direct file:line evidence, code is unambiguous.
  - R2: HIGH — direct file:line evidence, batch_dispatcher.py + worker.py confirm no streaming write path exists.
  - Symptom-2-not-regression: HIGH — wiring traced end-to-end with file:line citations, 404 contract is explicit in code comments and adapter docs.

fix:

  **Diagnose-only mode — no code changes applied. Recommended minimal patches (orchestrator can choose Fix now or Plan fix):**

  **Fix R1 — drop the round-entry clear, OR move it to a different signal field.**
  - File: src/alphaswarm/state.py, lines 131-136.
  - Option A (minimal-blast-radius): delete the clear entirely. Per-agent state will simply be overwritten by the next round's writes (when those start streaming after R2 fix). Stale R1 signals would persist visually for a round, but the frontend has `roundLastSpoke` semantics it can use to dim them.
    ```python
    # Before
    if phase in (SimulationPhase.ROUND_1, SimulationPhase.ROUND_2, SimulationPhase.ROUND_3):
        self._agent_states.clear()
    # After
    # (delete the block — agent_states are overwritten in place per agent_id by the next round)
    ```
  - Option B (preserve "thinking" semantics): instead of clearing, set every existing AgentState to a "thinking" placeholder so the frontend can render dim/pulsing dots:
    ```python
    if phase in (SimulationPhase.ROUND_1, SimulationPhase.ROUND_2, SimulationPhase.ROUND_3):
        self._agent_states = {
            aid: AgentState(signal=None, confidence=0.0)
            for aid in self._agent_states
        }
    ```
    This keeps the keys (so the dict size is non-zero immediately) but signals reset. Frontend frame.ts already normalises a None/missing signal to 'hold' at line 26-31; a small adapter tweak could surface a `thinking: true` flag.

  **Fix R2 — stream per-agent writes from inside the worker context manager.**
  - File: src/alphaswarm/worker.py (or batch_dispatcher.py:_safe_agent_inference). Add `update_agent_state` call right after each individual inference resolves.
  - Recommended location: worker.py inside the same block that already calls `update_tps` (lines 108-112), or in batch_dispatcher.py:_safe_agent_inference around line 73 right after `worker.infer()` returns.
  - Sketch (in batch_dispatcher.py:_safe_agent_inference, with state_store and agent_id threaded in):
    ```python
    async with agent_worker(persona, governor, client, model, state_store=state_store) as worker:
        decision = await worker.infer(...)
    if state_store is not None and decision.signal is not SignalType.PARSE_ERROR:
        await state_store.update_agent_state(persona["agent_id"], decision.signal, decision.confidence)
    return decision
    ```
  - Side effect: simulation.py's batch for-loops at 538-541 / 718-720 / 998-999 / 1131-1133 become redundant. They can be removed OR left as defensive "ensure all 100 are written" backstops (cheap — ~100 dict writes).

  **For symptom 2 (not-a-regression but UX is bad):**
  - File: frontend/src/components/v2.tsx, line 633. Bump `maxAttempts: 200` to a higher cap (e.g. 1200 = 60 min) to cover realistic wall-clock for the full advisory pipeline on M1 Max.
  - Optional: add a backend status endpoint (e.g. GET /api/advisory/{cycle_id}/status) returning {state: "synthesis_queued" | "orchestrator_loading" | "synthesizing" | "ready" | "failed"} so the frontend can show progress instead of just polling 404 forever. This is new feature work, not a bug fix.
  - Optional: log line `auto_advisory_trigger_accepted` (already in simulation_manager.py:37) is the truth-source for "did the trigger fire". Confirm it appears in uvicorn logs after cycle complete to definitively rule out a regression from runtime evidence (the static-code analysis is already conclusive that the wiring is intact).

  **Verification path (post-fix):**
  - After R1+R2 fix, `useAgents()` should populate progressively as workers finish inference (1 → 100 over the round duration). At round transition, the count stays at 100 (dict not cleared) and signals get overwritten by new round writes. Force graph dots fill in continuously.
  - Bracket bars and KPI Consensus already populate after each round via `compute_bracket_summaries` + `set_bracket_summaries`. Fixing R1+R2 will make them appear "earlier" because the agent_states under them is no longer empty at round boundaries.

verification:
  - pytest tests/test_state.py tests/test_batch_dispatcher.py: 51 passed (includes 3 new regression tests + 1 updated test for the new set_phase contract).
  - pytest broader suite (state/simulation/tui/web/auto_advisory): 225 passed; 4 deselected pre-existing format-string failures unrelated to this fix (_format_peer_context line format), verified pre-existing via git stash.
  - Full pytest: 911 passed (+3 vs clean master 908), 22 failed pre-existing (graph_integration Neo4j-dependent + report/seed_pipeline format issues). No regressions introduced.
  - Frontend: npm run check (tsc -b --noEmit) green; npm run build (vite build) green.
  - Pending human-verify: user must confirm in live workflow that (a) agent dots appear progressively during 14-18min round dispatch (not at round boundaries), and (b) AdvisoryV2 stays polling for the full ~60min window.

files_changed:
  - src/alphaswarm/state.py (R1: set_phase preserves keys, resets signals to None placeholder)
  - src/alphaswarm/batch_dispatcher.py (R2: _safe_agent_inference streams update_agent_state on success; skips on PARSE_ERROR)
  - src/alphaswarm/simulation.py (R2 cleanup: removed all 4 post-dispatch update_agent_state for-loops at ~538-541, ~717-720, ~996-999, ~1131-1133)
  - tests/test_state.py (updated test_set_phase_resets_agents → test_set_phase_preserves_agent_keys_resets_signals)
  - tests/test_batch_dispatcher.py (added 3 streaming-hook regression tests)
  - frontend/src/components/v2.tsx (symptom-2 UX: AdvisoryV2 maxAttempts 200 → 1200)
