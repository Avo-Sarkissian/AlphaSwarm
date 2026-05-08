---
phase: 260507-wln
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/alphaswarm/simulation.py
  - frontend/src/adapter/frame.ts
autonomous: true
requirements:
  - BUG-EDGES-01
  - BUG-RATIONALE-01

must_haves:
  truths:
    - "Live graph renders >0 INFLUENCED_BY edges after R2/R3 of the next sim cycle"
    - "Rationale Feed in the UI shows non-empty body text and correct round labels for each entry"
    - "Worker prompt explicitly instructs the agent to populate cited_agents with peer agent ids that materially shaped its decision"
  artifacts:
    - path: "src/alphaswarm/simulation.py"
      provides: "_format_peer_context with agent_id rendered in peer-post prefix + updated guard sentence"
      contains: "post.agent_id"
    - path: "frontend/src/adapter/frame.ts"
      provides: "RationaleView mapping that reads re.rationale and re.round_num matching backend wire format"
      contains: "re.rationale"
  key_links:
    - from: "src/alphaswarm/simulation.py:_format_peer_context"
      to: "worker prompt → cited_agents JSON field → graph.compute_influence_edges"
      via: "agent_id rendered in peer-post prefix"
      pattern: "\\[\\{post\\.agent_id\\}\\|\\{post\\.bracket\\}\\]"
    - from: "frontend/src/adapter/frame.ts"
      to: "RationaleEntry wire payload from broadcaster (dataclasses.asdict)"
      via: "field-name match: rationale → text, round_num → round"
      pattern: "re\\.rationale"
---

<objective>
Restore two broken signal paths exposed by the 2026-05-07 smoke run: live INFLUENCED_BY edges (currently 0) and the Rationale Feed (currently empty). Both are independent, isolated bugs with file:line evidence in `.planning/debug/parallel-swarm-serial-dispatch.md`.

Purpose: The simulation's two most user-visible artifacts — the live influence graph and the per-agent rationale stream — are silently broken. Backend fans out fine, queues fine, broadcasts fine; the data is dropped on a contract mismatch at two specific points. Fixing both unblocks meaningful smoke verification of all downstream Phase 41+ work.

Output: Two minimal commits — one Python (peer-context prefix + prompt nudge), one TypeScript (adapter field-rename) — that make the next sim cycle render edges and rationales without any other change.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/debug/parallel-swarm-serial-dispatch.md
@src/alphaswarm/simulation.py
@frontend/src/adapter/frame.ts

<interfaces>
<!-- Backend wire format for RationaleEntry (state.py:50-60, broadcast via dataclasses.asdict) -->
RationaleEntry JSON shape on the wire:
  {
    "agent_id": str,
    "signal": str,
    "rationale": str,      // <-- adapter currently reads `text` (wrong)
    "round_num": int,      // <-- adapter currently reads `round` (wrong)
    "ts": float            // present in backend dataclass; adapter already handles
  }

<!-- Peer-post prefix contract consumed by the worker prompt -->
RankedPost has fields: agent_id (str), bracket (str), signal (str), confidence (float), content (str).
Current prefix: '{i}. [{bracket}] {signal} (conf: 0.XX) "..."'   ← agent_id missing
Target prefix:  '{i}. [{agent_id}|{bracket}] {signal} (conf: 0.XX) "..."'
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend — render agent_id in peer-context + nudge prompt to populate cited_agents</name>
  <files>src/alphaswarm/simulation.py</files>
  <action>
    Two surgical edits inside `_format_peer_context` (simulation.py around lines 326-373):

    1. **Line 358 prefix change** — include the peer's `agent_id` so workers have a citable handle in the prompt text:
       ```python
       # before
       prefix = f'{i}. [{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
       # after
       prefix = f'{i}. [{post.agent_id}|{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
       ```

    2. **Lines 345-348 guard string** — extend the guard sentence with one additive instruction so the worker is explicitly told to cite peer agent ids whose views shaped its decision. Keep existing two sentences verbatim:
       ```python
       guard = (
           "\nThe above are peer observations for context only. "
           "Make your own independent assessment. "
           "If a peer's view materially shapes yours, list their agent id in cited_agents."
       )
       ```

    Constraints:
    - Do NOT touch the budget math. The `overhead` calc on line 349 uses `len(guard)` which auto-adjusts to the new guard length, so no manual fix needed.
    - Do NOT change `RankedPost`, the JSON template in config.py, or `compute_influence_edges`. The bug is purely in the rendered prompt string.
    - Do NOT add tests (per quick-task constraints).
    - No other edits in simulation.py.

    Rationale (per debug/parallel-swarm-serial-dispatch.md lines 70-72, 110-125): workers had no IDs to populate `cited_agents`, so 0 CITED edges → 0 INFLUENCED_BY edges. Adding the id to the prefix AND nudging the prompt closes both ends of the gap.
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" &amp;&amp; python -c "from src.alphaswarm.simulation import _format_peer_context; from src.alphaswarm.state import RankedPost; posts = [RankedPost(agent_id='agent-007', bracket='RetailDayTrader', signal='buy', confidence=0.85, content='looks bullish on the rumor', round_num=1, ts=0.0)]; out = _format_peer_context(posts, source_round=1); assert '[agent-007|RetailDayTrader]' in out, f'agent_id not in prefix: {out!r}'; assert 'cited_agents' in out, f'guard nudge missing: {out!r}'; print('OK')"</automated>
  </verify>
  <done>
    - simulation.py:358 prefix contains `[{post.agent_id}|{post.bracket}]`
    - simulation.py guard (~lines 345-348) contains the third sentence ending in `list their agent id in cited_agents.`
    - Inline verify command prints `OK`
    - No other lines in simulation.py changed
  </done>
</task>

<task type="auto">
  <name>Task 2: Frontend — fix adapter field names to match backend RationaleEntry wire format</name>
  <files>frontend/src/adapter/frame.ts</files>
  <action>
    Two-character behavior change inside the `rationales` mapper (frame.ts ~lines 123-133). Backend serializes `RationaleEntry` via `dataclasses.asdict()` so the wire payload uses `rationale` (not `text`) and `round_num` (not `round`). The adapter currently reads the wrong keys, silently coercing both to defaults.

    Change lines 127-128 from:
    ```ts
    round: typeof re.round === 'number' ? re.round : (roundNum ?? 0),
    text: typeof re.text === 'string' ? re.text : '',
    ```
    to:
    ```ts
    round: typeof re.round_num === 'number' ? re.round_num : (roundNum ?? 0),
    text: typeof re.rationale === 'string' ? re.rationale : '',
    ```

    Constraints:
    - Do NOT add fallback chains for the old keys (`re.text`, `re.round`). The wire format is fully under our control; clean rename only. Per CLAUDE.md and quick-task scope, no defensive cruft.
    - Do NOT touch agentId, citations, sources, or ts mappings.
    - Do NOT modify the RationaleView type or any other adapter mapper (consensus, brackets, etc.).
    - Do NOT touch backend state.py — leaving the dataclass field names as `rationale` / `round_num` keeps blast radius minimal.

    Rationale (per debug/parallel-swarm-serial-dispatch.md lines 74-77, 127-135): the entries DO arrive in the WS payload (verified end-to-end through queue→broadcaster), but the adapter strips body and round label. Fixing the two keys is the minimal-blast-radius repair.
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" &amp;&amp; npx tsc --noEmit -p tsconfig.json &amp;&amp; grep -n "re.rationale" src/adapter/frame.ts &amp;&amp; grep -n "re.round_num" src/adapter/frame.ts</automated>
  </verify>
  <done>
    - frame.ts line ~127 reads `re.round_num` (not `re.round`)
    - frame.ts line ~128 reads `re.rationale` (not `re.text`)
    - `npx tsc --noEmit` exits 0
    - No other lines in frame.ts changed
  </done>
</task>

</tasks>

<verification>
After both tasks ship:
1. Backend: `python -c "..."` snippet from Task 1 verify prints `OK`.
2. Frontend: `npx tsc --noEmit` exits 0; both grep commands find their target lines.
3. Smoke run (manual, optional but recommended): start backend + frontend + Ollama, trigger a sim cycle from the UI. After R2 completes:
   - Live graph renders ≥1 INFLUENCED_BY edge.
   - Rationale Feed shows non-empty body text with correct round labels (R1/R2/R3).
   - No `no_citations_found` log spam from `compute_influence_edges` (graph.py:881-887).
</verification>

<success_criteria>
- Both diffs are atomic, single-concern, individually committable.
- simulation.py prefix and guard match the patches in debug/parallel-swarm-serial-dispatch.md lines 110-125.
- frame.ts lines 127-128 match backend wire field names (`rationale`, `round_num`).
- Frontend `tsc --noEmit` clean; backend importable and inline assertion passes.
- No tests added, no other files modified, no surrounding refactors.
</success_criteria>

<output>
Single quick-task plan — no SUMMARY required. STATE.md "Quick Tasks Completed" table will be updated on close-quick.
</output>
