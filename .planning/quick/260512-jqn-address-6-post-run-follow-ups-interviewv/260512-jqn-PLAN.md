---
phase: quick-260512-jqn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  # ITEM 1 — InterviewV2 + Onboarding + BracketDeepDive CSS
  - frontend/src/styles.css
  # ITEM 2 — /api/edges Cypher fix
  - src/alphaswarm/web/routes/edges.py
  - src/alphaswarm/graph.py
  - tests/test_edges_route.py
  # ITEM 3 — Governor slot metrics in WS frame
  - src/alphaswarm/state.py
  - src/alphaswarm/governor.py
  - frontend/src/adapter/frame.ts
  # ITEM 4 — Rationale sliding window
  - src/alphaswarm/web/broadcaster.py
  - src/alphaswarm/batch_dispatcher.py
  - src/alphaswarm/simulation.py
  - frontend/src/context/RationalesContext.tsx
  - tests/test_state.py
  - tests/test_batch_dispatcher.py
  # ITEM 5 — SignalWire live audit
  - src/alphaswarm/data_audit.py
  - src/alphaswarm/web/broadcaster.py
  - frontend/src/components/v2.tsx
  - frontend/src/hooks/useDataSourceAudit.ts
  - frontend/src/adapter/frame.ts
  - tests/test_data_audit.py
  # ITEM 6 — Advisory items[] + sector enrichment + frontend fallback
  - src/alphaswarm/advisory/prompt.py
  - src/alphaswarm/advisory/sector_map.py
  - src/alphaswarm/advisory/engine.py
  - src/alphaswarm/advisory/types.py
  - tests/test_advisory_synthesize.py
autonomous: true
requirements:
  - POST-RUN-FU-01  # InterviewV2 + Onboarding + BracketDeepDive CSS gap
  - POST-RUN-FU-02  # /api/edges Cypher fix
  - POST-RUN-FU-03  # Governor slot metrics in WS (closes KR-41.1-05)
  - POST-RUN-FU-04  # Rationale sliding window (closes tasks #4 + #9)
  - POST-RUN-FU-05  # SignalWire live API audit
  - POST-RUN-FU-06  # Advisory items[] fix + sector enrichment + frontend fallback (closes task #10)

must_haves:
  truths:
    - "Clicking an agent dot opens InterviewV2 as a full-screen modal with all CSS classes resolved (not a glitched strip)"
    - "GET /api/edges/{cycle_id}?round=3 returns a non-empty edges array for a cycle that completed 100 R3 decisions"
    - "PARALLEL SLOTS KPI tile shows live numerator/denominator (e.g. 12/16) during dispatch — never frozen at 0/16"
    - "Rationale Feed populates progressively during R1 inference (not just at round boundaries) and survives WS reconnect"
    - "SignalWire ticker scrolls live yfinance/FRED/other provider calls — no SIGNAL_WIRE_SEED literal in dist bundle"
    - "AdvisoryV2 Holdings tab renders one card per holding (full 32-unique-ticker portfolio) even when LLM omits some items"
    - "Backend test suite green for touched modules; frontend npm run check && npm run build green"
  artifacts:
    - path: "frontend/src/styles.css"
      provides: "Comprehensive CSS for iv-* / interview-* / agent-* / onboarding-* / ob-* / bdd-* / bracket-deep-* classes"
      contains: ".iv-takeover"
    - path: "src/alphaswarm/web/routes/edges.py"
      provides: "GET /api/edges/{cycle_id} route returning non-empty edges for cycles with R3 data"
    - path: "tests/test_edges_route.py"
      provides: "Regression test asserting non-empty edges array from /api/edges route"
      contains: "def test_edges_route"
    - path: "src/alphaswarm/state.py"
      provides: "GovernorMetrics (current_slots + active_count already exist per state.py:23-24); _rationale_window deque(maxlen=50)"
      contains: "current_slots"
    - path: "src/alphaswarm/batch_dispatcher.py"
      provides: "_safe_agent_inference streams push_rationale per-agent after worker.infer()"
      contains: "push_rationale"
    - path: "frontend/src/context/RationalesContext.tsx"
      provides: "Simplified one-line context reading frame.rationales (no accumulator/dedup); keeps existing frame: StateFrame prop signature"
    - path: "src/alphaswarm/data_audit.py"
      provides: "Audit buffer (deque maxlen=100) + helpers to record provider calls"
      contains: "DataSourceAuditBuffer"
    - path: "tests/test_data_audit.py"
      provides: "Regression test for DataSourceAuditEntry + DataSourceAuditBuffer record/snapshot/cap behavior"
      contains: "def test_data_audit"
    - path: "frontend/src/hooks/useDataSourceAudit.ts"
      provides: "Hook reading data_source_audit from WS frame; returns [] when empty"
      contains: "useDataSourceAudit"
    - path: "src/alphaswarm/advisory/sector_map.py"
      provides: "Curated ticker→sector map covering the 32 unique user tickers + UNKNOWN default"
      contains: "AAPL"
    - path: "src/alphaswarm/advisory/prompt.py"
      provides: "Rewritten prompt: one item per holding; HOLD@0.2-0.4 placeholder; redefined affected_holdings"
      contains: "NEVER OMIT"
    - path: "tests/test_advisory_synthesize.py"
      provides: "Regression test asserting items count == holdings count from rewritten prompt path"
      contains: "def test_advisory"
  key_links:
    - from: "frontend/src/components/interview_v2.tsx"
      to: "frontend/src/styles.css"
      via: "className iv-* / agent-* class references resolved by new CSS block"
      pattern: "\\.iv-takeover|\\.iv-header|\\.iv-body"
    - from: "frontend/src/components/v2.tsx (SignalWire)"
      to: "frontend/src/hooks/useDataSourceAudit.ts"
      via: "useDataSourceAudit() instead of mocks/sources dynamic import"
      pattern: "useDataSourceAudit"
    - from: "src/alphaswarm/batch_dispatcher.py"
      to: "src/alphaswarm/state.py"
      via: "state_store.push_rationale(RationaleEntry(...)) inside _safe_agent_inference"
      pattern: "push_rationale"
    - from: "src/alphaswarm/web/broadcaster.py"
      to: "src/alphaswarm/state.py"
      via: "snapshot().rationale_entries reads _rationale_window deque (no drain)"
      pattern: "rationale_entries"
    - from: "frontend/src/adapter/frame.ts"
      to: "src/alphaswarm/state.py (GovernorMetrics)"
      via: "Reads governor_metrics.current_slots / active_count; drops the {0, 8} stub"
      pattern: "current_slots|active_count"
    - from: "src/alphaswarm/advisory/engine.py"
      to: "src/alphaswarm/advisory/sector_map.py"
      via: "Per-holding enrichment lookup before prompt build"
      pattern: "from .sector_map|SECTOR_MAP"
---

<objective>
Close 6 post-run follow-ups surfaced during the 2026-05-10/11 41.6 live UAT against cycle 7ab3984d-36a5-4d6a-9178-bfaa842b15d2. Each item is an atomic, independently committable fix; the plan deliberately bundles all 6 into ONE plan because each task is narrow and self-contained (1-3 files of focused change). The dashboard already renders structurally but currently has: (1) a takeover-modal CSS gap that makes 3 new W4 components render as glitched strips, (2) a broken /api/edges Cypher that returns 0 edges despite cycle completion, (3) hard-coded governor slot KPI of 0/8, (4) rationale UI losing state after round transitions, (5) SignalWire ticker still consuming the DEV mock seed, and (6) AdvisoryV2 returning items=[] because the prompt explicitly OMITS holdings without strong signals.

Purpose: Make the live UAT actually pass end-to-end. After this plan, a fresh sim from Idle → Onboarding → 3-round dispatch → AdvisoryV2 should render every surface with real data, no mocks in production bundle, and a complete portfolio view (32 unique tickers from the user's Schwab + Roth holdings) for the advisory report.

Output: 6 atomic git commits (one per ITEM), each with green build/test gates. Backend touches: state.py, governor.py, broadcaster.py, batch_dispatcher.py, simulation.py, advisory/*. Frontend touches: styles.css, frame.ts, v2.tsx, RationalesContext.tsx, hooks/useDataSourceAudit.ts. Two new modules: data_audit.py, advisory/sector_map.py. Three new test files: test_edges_route.py, test_data_audit.py, test_advisory_synthesize.py (test_state + test_batch_dispatcher updated).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@CLAUDE.md
@.planning/phases/41.6-ui-revamp-alphaswarm-2-quant-terminal-port-and-wire/41.6-HANDOFF.md
@.planning/phases/41.6-ui-revamp-alphaswarm-2-quant-terminal-port-and-wire/41.6-04-SUMMARY.md
@.planning/debug/ws-agent-states-not-emitted-mid-sim.md
@frontend/src/components/interview_v2.tsx
@frontend/src/components/onboarding.tsx
@frontend/src/components/bracket_deep.tsx
@frontend/src/components/v2.tsx
@frontend/src/components/panels.jsx
@frontend/src/styles.css
@frontend/src/adapter/frame.ts
@frontend/src/context/RationalesContext.tsx
@frontend/src/App.tsx
@src/alphaswarm/state.py
@src/alphaswarm/governor.py
@src/alphaswarm/web/broadcaster.py
@src/alphaswarm/web/routes/edges.py
@src/alphaswarm/graph.py
@src/alphaswarm/batch_dispatcher.py
@src/alphaswarm/simulation.py
@src/alphaswarm/advisory/prompt.py
@src/alphaswarm/advisory/engine.py
@src/alphaswarm/advisory/types.py

<interfaces>
<!-- Verified contracts the executor MUST honor. Do not invent. -->

From src/alphaswarm/state.py (already verified by debug doc + checker — state.py:23-24):
```python
@dataclass(frozen=True)
class RationaleEntry:
    agent_id: str
    signal: SignalType | None
    rationale: str
    round_num: int
    # Wire field name on the frontend adapter is `round_num` (frame.ts:120-133)

@dataclass(frozen=True)
class GovernorMetrics:
    # FIELDS ALREADY DECLARED (state.py:23-24, populated by governor.py:391-400):
    #   current_slots: int
    #   active_count: int
    # ITEM 3 is therefore verify-only on the backend — go straight to frame.ts swap.
    ...

class StateStore:
    async def push_rationale(self, entry: RationaleEntry) -> None: ...
    # CURRENTLY: drain-based via asyncio.Queue. REPLACE WITH: deque(maxlen=50) + append.
    def snapshot(self) -> StateSnapshot: ...
    async def update_agent_state(self, agent_id: str, signal, confidence: float) -> None: ...
    async def set_phase(self, phase: SimulationPhase) -> None: ...
```

From src/alphaswarm/web/routes/edges.py (response envelope — DO NOT break this shape):
```python
class EdgesResponse(BaseModel):
    edges: list[EdgeItem]  # NOT a flat array — envelope is { "edges": [...] }

class EdgeItem(BaseModel):
    source_id: str  # citing agent (author of decision that contained citation)
    target_id: str  # cited agent
```
Direction semantic encoded once in frontend/src/api/edges.ts JSDoc (codex MEDIUM-7).

From src/alphaswarm/web/broadcaster.py:88-96 (current wire path — adapt for ITEM 4):
```python
snap = state_store.snapshot()
rationales = state_store.drain_rationales(5)   # REMOVE in ITEM 4
d = dataclasses.asdict(snap)
d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]  # REMOVE override
```

From frontend/src/adapter/frame.ts:120-133 (rationale adapter — already correct):
```ts
re.rationale, re.round_num   // matches RationaleEntry wire shape
```

From frontend/src/App.tsx:68 (existing call-site for RationalesProvider — DO NOT CHANGE):
```tsx
<RationalesProvider frame={lastFrame}>
  ...
</RationalesProvider>
```
The `frame: StateFrame` prop signature MUST be preserved. ITEM 4 simplifies ONLY the provider internals (drop useState accumulator, useEffect, dedup Set — back to one-line useMemo over `frame.rationales`).

From frontend/src/context/RationalesContext.tsx (current accumulator — SIMPLIFY in ITEM 4):
Public hook contract `useRationales(): { rationales: RationaleView[] }` MUST NOT CHANGE.
The component signature `RationalesProvider({ frame, children })` MUST NOT CHANGE.
Internals may drop useState/useEffect accumulator + dedup — that's the whole point.

CONTRACT.md §2.1 frontend hook return shapes — UNCHANGED for all items:
- useAgents(): { agents: AgentView[] }
- useBrackets(): { brackets: BracketView[] }
- useTelemetry(): { tps, slots: {used,max}, ...dataSourceAudit? }
- useRationales(): { rationales: RationaleView[] }
- useCurrentCycle(): { cycleId: string | null }

Hard frontend rules (project memory + CLAUDE.md):
- interview_v2.tsx / onboarding.tsx / bracket_deep.tsx STAY .tsx (codex HIGH-1)
- panels.jsx STAYS .jsx — NO TS syntax
- mocks/wire.ts + mocks/sources.ts stay on disk as DEV fallback; ITEM 5 REPLACES the consumer
- No window.AS_DATA / window.Icon
- Use existing CSS vars: --bg, --bg-2, --accent, --buy, --sell, --hold, --text, --text-2, --text-3, --border, --border-2
</interfaces>

</context>

<tasks>

<task type="auto">
  <name>Task 1 [ITEM 1]: InterviewV2 + Onboarding + BracketDeepDive CSS gap</name>
  <files>frontend/src/styles.css</files>
  <action>
  Reference (read-only) `frontend/src/components/{interview_v2.tsx, onboarding.tsx, bracket_deep.tsx}` to enumerate every undefined class name. Grep helpers:

  ```bash
  cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm"
  grep -hoE 'className="[^"]+"' frontend/src/components/interview_v2.tsx frontend/src/components/onboarding.tsx frontend/src/components/bracket_deep.tsx | sort -u
  # Cross-check existing styles.css for each class. Missing classes → add.
  ```

  Add a comprehensive CSS block at the bottom of `frontend/src/styles.css`, following the same pattern as `.adv-takeover` (commit `1077eec`) and `.ds-takeover` (commit `f4909ba`). Use existing CSS vars ONLY — no hex literals.

  **InterviewV2 layout target:**
  - `.iv-takeover` — full-screen overlay, position fixed, inset 0, z-index 200, `background: var(--bg)`, display flex column.
  - `.iv-header` — agent-info row (avatar + ID + bracket pill + signal pill + confidence + close button); padding 16px, border-bottom 1px solid var(--border).
  - `.iv-avatar` — 40x40 circle, bracket-color accent.
  - `.iv-id` — large font, var(--text).
  - `.iv-bracket-pill` — small pill, bracket-color background, var(--text) text.
  - `.iv-signal-pill` — BUY=var(--buy), SELL=var(--sell), HOLD=var(--hold). Use modifier classes `.iv-signal-pill--buy`, `--sell`, `--hold`.
  - `.iv-confidence` — var(--text-2) muted.
  - `.iv-close` — top-right, var(--text-3) → var(--text) on hover.
  - `.iv-body` — flex row, flex 1, overflow hidden.
  - `.iv-sidebar` — left rail, 280px, border-right 1px solid var(--border), padding 16px, var(--bg-2).
    - `.iv-stats-section` — block per stat group.
    - `.iv-stat-label` — uppercase, var(--text-3), font-size 11px, letter-spacing 1px.
    - `.iv-stat-value` — large, var(--text), font-variant-numeric tabular-nums.
    - `.iv-stat-row` — flex row, label left, value right.
    - Stats to style: CYCLE STATS / READ / CITED-BY / OUT-DEGREE / IN-DEGREE / PEER READS / SHOCK IMPACT / DATA SOURCES.
  - `.iv-chat` — right panel, flex 1 column, padding 16px.
  - `.iv-tabs` — tab row (Interview / Rationale Log), border-bottom; active tab var(--accent) underline.
  - `.iv-tab` + `.iv-tab--active`.
  - `.iv-messages` — flex 1, overflow-y auto, padding-bottom 12px.
  - `.iv-message` — message bubble; modifier `.iv-message--user` (right-aligned, var(--accent) background) vs `.iv-message--agent` (left-aligned, var(--bg-2)).
  - `.iv-quick-replies` — chip row, flex wrap gap 8px, padding 8px 0.
  - `.iv-chip` — pill, var(--bg-2) bg, hover var(--border-2); on click → fills input.
  - `.iv-input-row` — flex row, input + send button.
  - `.iv-input` — flex 1, var(--bg-2), border var(--border), color var(--text).
  - `.iv-send` — var(--accent) bg, var(--bg) text.
  - `.iv-rationale-list` — used by Rationale Log tab; entries grouped by round.
  - `.iv-rationale-entry` + `.iv-rationale-round-header`.

  **Onboarding layout target (3-step):**
  - `.ob-takeover` — full-screen overlay, z-index 250 (above iv), `background: var(--bg)`, center content.
  - `.ob-container` — max-width 720px, margin auto, padding 32px.
  - `.ob-step` — visible step container.
  - `.ob-step-header` — large title var(--text), subtitle var(--text-2).
  - `.ob-step-progress` — dots row at top; `.ob-dot` + `.ob-dot--active`.
  - `.ob-health-row` — flex row for /api/health gate; status badge (OK var(--buy), FAIL var(--sell), LOADING var(--text-3)).
  - `.ob-model-list` — list of model rows, each `.ob-model-row` + `.ob-model-row--selected` (border var(--accent)).
  - `.ob-model-recommended-badge` — small pill, var(--accent) bg.
  - `.ob-seed-textarea` — large textarea, var(--bg-2), border var(--border).
  - `.ob-example-chips` — chip row for example seeds.
  - `.ob-actions` — bottom button row: `.ob-btn-back` + `.ob-btn-next` + `.ob-btn-run`; `.ob-btn-disabled` greyed.

  **BracketDeepDive layout target:**
  - `.bdd-takeover` — full-screen overlay, z-index 200, `background: var(--bg)`.
  - `.bdd-header` — bracket name + close; bracket-color accent strip.
  - `.bdd-body` — grid 2 columns: left member list, right stats panel.
  - `.bdd-member-list` — scrollable list of agents.
  - `.bdd-member-row` — flex row: agent ID + signal pill + confidence + out/in counts. Click → onAgentInterview.
  - `.bdd-member-row:hover` — var(--bg-2).
  - `.bdd-stats` — right panel; aggregate stats per bracket.
  - `.bdd-stat-card` — block per stat.
  - `.bdd-no-edges` — placeholder when hasEdges=false, renders "—" muted.

  Also audit and add any other invented classes found by the grep that fall through. Keep CSS additive — do NOT modify existing rules.

  Use existing project pattern: each component block prefixed with a comment header like:
  ```css
  /* ============================================================
     InterviewV2 — full-screen agent takeover (ITEM 1, 260512-jqn)
     ============================================================ */
  ```
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npm run check && npm run build</automated>
  Manual: start `npm run dev`, open dashboard, click any agent node → InterviewV2 renders as proper full-screen modal with header + 2-column body (not a glitched strip). Open settings or trigger Onboarding (clear localStorage `as_onboarding_v1_complete`, reload) → Onboarding renders centered with progress dots and step content. Click any bracket row → BracketDeepDive renders with member list + stats panel.
  </verify>
  <done>
  - Every class name in interview_v2.tsx / onboarding.tsx / bracket_deep.tsx resolves to a CSS rule in styles.css (verified by grep diff).
  - `npm run check` exits 0; `npm run build` exits 0.
  - Visual: each of the 3 takeovers renders correctly (no fallback to default block layout).
  - Single atomic commit: `fix(41.6-04): port missing CSS for InterviewV2 + Onboarding + BracketDeepDive takeovers`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2 [ITEM 2]: /api/edges Cypher fix + regression test</name>
  <files>src/alphaswarm/web/routes/edges.py, src/alphaswarm/graph.py, tests/test_edges_route.py</files>
  <behavior>
    - GIVEN a cycle that has completed 100 R3 decisions with peer citations
      WHEN GET /api/edges/{cycle_id}?round=3 is called
      THEN the response is `{"edges": [...]}` with len(edges) > 0
      AND each edge has source_id (citing agent) + target_id (cited agent)
    - GIVEN a cycle that does not exist
      WHEN GET /api/edges/{cycle_id}?round=3 is called
      THEN the response is `{"edges": []}` (empty, NOT 404 — keeps frontend contract)
    - GIVEN a cycle with no round=N data
      WHEN GET /api/edges/{cycle_id}?round=N is called
      THEN the response is `{"edges": []}` (empty)
  </behavior>
  <action>
  **Step 1 — Live probe to determine producer-side vs route-side bug.**

  Cycle to probe: `7ab3984d-36a5-4d6a-9178-bfaa842b15d2` (per task spec — confirmed 100 R3 decisions via `/api/replay/cycles`).

  ```bash
  # Direct Cypher probe — connect via docker exec to the running `neo4j` container (NOT alphaswarm-neo4j — see 41.6-HANDOFF.md "Neo4j gotcha")
  docker exec -i neo4j cypher-shell -u neo4j -p alphaswarm "MATCH (a:Agent)-[r:INFLUENCED_BY {cycle_id: '7ab3984d-36a5-4d6a-9178-bfaa842b15d2'}]->(b:Agent) RETURN count(r) AS n;"
  ```

  Interpret:
  - If `n > 0` → relationships exist; bug is in route Cypher (filter mismatch, round property mismatch, direction reversed). Fix the route.
  - If `n == 0` → check INFLUENCED_BY without filter: `MATCH ()-[r:INFLUENCED_BY]->() RETURN keys(r), r LIMIT 5;`. The property name might be `round_num` not `cycle_id`, or `cycleId` (camelCase), or relationships might be on a Decision node instead of Agent→Agent.

  Cross-reference with `src/alphaswarm/graph.py:942` (per 41.6-04 SUMMARY): `MATCH (author:Agent)-[:MADE]->(d:Decision)-[:CITED]->(cited:Agent) ... RETURN DISTINCT author.id AS source_id, cited.id AS target_id`. AND `src/alphaswarm/graph.py:974`: `CREATE (src)-[:INFLUENCED_BY]->(tgt)` where src=author, tgt=cited. So the relationship IS Agent→Agent (INFLUENCED_BY), but the route query must filter on the right `cycle_id` property AND the right `round_num` property.

  **Step 2 — Inspect existing route handler at `src/alphaswarm/web/routes/edges.py`.**

  Read the entire file. Most likely bugs:
  - Round filter property: `r.round` vs `r.round_num` vs `r.round_number` (check graph.py CREATE statement).
  - cycle_id filter: on relationship (`r.cycle_id`) vs on node (`a.cycle_id`).
  - Direction reversed: `(a)-[r:INFLUENCED_BY]->(b)` vs `(a)<-[r:INFLUENCED_BY]-(b)`.
  - Property case sensitivity: `cycleId` vs `cycle_id`.

  **Step 3 — Fix the Cypher in `src/alphaswarm/web/routes/edges.py`.**

  After identifying the actual stored property names (from `keys(r)` probe), rewrite the query. Likely shape:
  ```cypher
  MATCH (a:Agent)-[r:INFLUENCED_BY]->(b:Agent)
  WHERE r.cycle_id = $cycle_id AND r.round_num = $round
  RETURN DISTINCT a.id AS source_id, b.id AS target_id
  ```
  Whatever the stored property is — match it exactly. If the read helper lives in `src/alphaswarm/graph.py` (likely a `read_*edges*` or `read_influence*` method), fix it there and have the route call it. Otherwise inline the query in the route.

  Response shape MUST stay `{"edges": [{"source_id": ..., "target_id": ...}, ...]}` (per CONTRACT — frontend `api/edges.ts` declares EdgesResponse envelope).

  **Step 4 — Write regression test `tests/test_edges_route.py`.**

  RED first:
  ```python
  import pytest
  from httpx import ASGITransport, AsyncClient
  from alphaswarm.web.app import app

  @pytest.mark.asyncio
  async def test_edges_route_returns_non_empty_for_completed_cycle(monkeypatch):
      """Regression: /api/edges/{cycle_id}?round=3 must return non-empty edges for cycle with R3 data."""
      # Mock graph_manager.read_*edges* method to return fixture data
      fixture_edges = [
          {"source_id": "Q-01", "target_id": "I-04"},
          {"source_id": "Q-02", "target_id": "D-07"},
          {"source_id": "M-05", "target_id": "Q-01"},
      ]
      # Patch the actual method name used by the route — verify by reading graph.py
      from alphaswarm.web.routes import edges as edges_route
      async def fake_read(cycle_id: str, round_num: int):
          assert cycle_id == "test-cycle"
          assert round_num == 3
          return fixture_edges
      monkeypatch.setattr(edges_route, "_read_edges_for_round", fake_read, raising=False)
      # If the route calls graph_manager.read_*, patch on the app.state.graph_manager instead

      transport = ASGITransport(app=app)
      async with AsyncClient(transport=transport, base_url="http://test") as client:
          resp = await client.get("/api/edges/test-cycle?round=3")
      assert resp.status_code == 200
      body = resp.json()
      assert "edges" in body
      assert len(body["edges"]) == 3
      assert body["edges"][0] == {"source_id": "Q-01", "target_id": "I-04"}

  @pytest.mark.asyncio
  async def test_edges_route_empty_for_missing_cycle(monkeypatch):
      """Missing cycle → empty edges array, NOT 404."""
      from alphaswarm.web.routes import edges as edges_route
      async def fake_read_empty(cycle_id: str, round_num: int):
          return []
      monkeypatch.setattr(edges_route, "_read_edges_for_round", fake_read_empty, raising=False)
      transport = ASGITransport(app=app)
      async with AsyncClient(transport=transport, base_url="http://test") as client:
          resp = await client.get("/api/edges/missing?round=3")
      assert resp.status_code == 200
      assert resp.json() == {"edges": []}
  ```

  Adjust the patch target after reading the actual route code. The test MUST fail with the current code (or be GREEN if the live probe revealed no production bug — in which case there's a different bug or it's already working and the symptom was elsewhere). Then make it pass after the Cypher fix.

  **Step 5 — Verify against the live cycle.**

  ```bash
  curl -s 'http://localhost:8000/api/edges/7ab3984d-36a5-4d6a-9178-bfaa842b15d2?round=3' | jq '.edges | length'
  # MUST return > 0
  ```
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/test_edges_route.py -x -q</automated>
  Live probe: `curl -s 'http://localhost:8000/api/edges/7ab3984d-36a5-4d6a-9178-bfaa842b15d2?round=3' | jq '.edges | length'` returns > 0.
  </verify>
  <done>
  - Live curl probe returns edges count > 0.
  - `tests/test_edges_route.py` passes.
  - Existing test suite still green for touched modules (`uv run pytest tests/test_edges_route.py tests/test_web*.py -x -q`).
  - Single atomic commit: `fix(api): /api/edges Cypher returns edges for completed cycle (incl. regression test)`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3 [ITEM 3]: Governor slot metrics in WS frame (closes KR-41.1-05)</name>
  <files>src/alphaswarm/state.py, src/alphaswarm/governor.py, frontend/src/adapter/frame.ts</files>
  <behavior>
    - GIVEN a sim mid-dispatch with the governor pool managing concurrency
      WHEN the broadcaster emits a snapshot
      THEN governor_metrics carries `current_slots` (max concurrent budget) and `active_count` (currently running)
      AND frame.ts surfaces `telemetry.slots = { used: active_count, max: current_slots }`
      AND the PARALLEL SLOTS KPI tile shows live numerator/denominator (never frozen at 0/16)
  </behavior>
  <action>
  **NOTE (checker-confirmed):** Steps 1-2 below are VERIFY-ONLY. The `current_slots` and `active_count` fields already exist on `GovernorMetrics` (state.py:23-24) and are already populated by `governor.py:391-400`. The remaining real work is in Step 5 (frame.ts swap). Steps 3-4 are also already-done; just confirm by reading the files. Step 6 adds the regression test that fixates the contract.

  **Step 1 — Verify GovernorMetrics fields exist (READ ONLY).**

  Open `src/alphaswarm/state.py` and confirm at ~line 23-24:
  ```python
  @dataclass(frozen=True)
  class GovernorMetrics:
      # ... existing fields ...
      current_slots: int = ...   # ALREADY PRESENT
      active_count: int = ...    # ALREADY PRESENT
  ```
  If the fields are NOT present (checker was wrong), fall back to "add them" — but the expectation is they ARE present. Do NOT re-add.

  **Step 2 — Verify governor.py populates them (READ ONLY).**

  Open `src/alphaswarm/governor.py` and confirm at ~lines 391-400 that the `state_store.update_governor_metrics(...)` (or equivalent setter) call passes `current_slots=...` and `active_count=...`. If yes → no change needed in governor.py at all. Note this in your task journal.

  **Step 3 — Broadcaster passthrough (READ ONLY).**

  `broadcaster.py` serializes governor_metrics via `dataclasses.asdict(snap)`. New fields propagate automatically — verify by reading `src/alphaswarm/web/broadcaster.py:88-96`. No change required UNLESS the broadcaster cherry-picks a subset of fields (read first; only patch if needed). Expected: no patch needed.

  **Step 4 — (skipped; nothing to do — collapsed into Step 5).**

  **Step 5 — Frontend adapter (THE REAL WORK).**

  In `frontend/src/adapter/frame.ts`, find the existing `{slotsUsed: 0, slotsMax: 8}` stub (KR-41.1-05 stub). Replace with:
  ```ts
  const gm = r.governor_metrics ?? {};
  const slotsUsed = typeof gm.active_count === 'number' ? gm.active_count : 0;
  const slotsMax = typeof gm.current_slots === 'number' ? gm.current_slots : 0;
  // ... existing telemetry shape ...
  telemetry.slots = { used: slotsUsed, max: slotsMax };
  ```

  Make sure the existing `useTelemetry()` consumers in `panels.jsx` (KPI tile reads `slots`) still receive the same shape — no change in hook contract.

  **Step 6 — Tests.**

  Update tests under `tests/test_state.py` / `tests/test_governor*.py` (whichever asserts GovernorMetrics shape) to:
  - Include the two new fields in any fixture/expected snapshot (these may already exist if the fields are pre-declared — verify and only add if missing).
  - Add an explicit test asserting the broadcaster snapshot carries both fields:
    ```python
    @pytest.mark.asyncio
    async def test_governor_metrics_includes_slots():
        store = StateStore()
        await store.update_governor_metrics(..., current_slots=16, active_count=12)
        snap = store.snapshot()
        assert snap.governor_metrics.current_slots == 16
        assert snap.governor_metrics.active_count == 12
        d = dataclasses.asdict(snap)
        assert d["governor_metrics"]["current_slots"] == 16
        assert d["governor_metrics"]["active_count"] == 12
    ```

  If any existing test asserted the old `{slotsUsed: 0, slotsMax: 8}` baseline on the FRONTEND adapter (vitest), update it to the new dynamic values (no test exists today for frame.ts, so just verify by build + manual).
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/test_state.py -x -q && (compgen -G "tests/test_governor*.py" > /dev/null && uv run pytest tests/test_governor*.py -x -q || true) && cd frontend && npm run check && npm run build</automated>
  Live: trigger a sim, observe `PARALLEL SLOTS` KPI tile shows a non-zero numerator (e.g., 12/16) during dispatch. After dispatch quiesces, numerator drops to 0 while denominator stays at the budget.
  </verify>
  <done>
  - GovernorMetrics has `current_slots: int` + `active_count: int` (confirmed pre-existing per checker).
  - governor.py populates both fields on every metrics update (confirmed pre-existing per checker).
  - frame.ts reads from `governor_metrics.current_slots / active_count`; the `{0, 8}` stub is gone.
  - KR-41.1-05 stub note in any KR audit file referenced as CLOSED (or marked partial→closed) — if a KR register file exists in `.planning/phases/41.6-*/41.6-KR-AUDIT.md`, append a one-line note. Otherwise skip (out-of-scope for quick task).
  - Backend tests green. Frontend build green.
  - Single atomic commit: `feat(state): emit governor current_slots + active_count in WS frame (closes KR-41.1-05)`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4 [ITEM 4]: Rationale sliding window refactor (closes tasks #4 + #9)</name>
  <files>src/alphaswarm/state.py, src/alphaswarm/web/broadcaster.py, src/alphaswarm/batch_dispatcher.py, src/alphaswarm/simulation.py, frontend/src/context/RationalesContext.tsx, tests/test_state.py, tests/test_batch_dispatcher.py</files>
  <behavior>
    - GIVEN a fresh StateStore
      WHEN push_rationale is called 60 times
      THEN snapshot().rationale_entries returns the last 50 entries in insertion order (deque maxlen=50)
      AND no entries are drained — peek-only semantics
    - GIVEN a sim mid-round in batch_dispatcher
      WHEN _safe_agent_inference completes for a single agent
      THEN state_store.push_rationale is called with a RationaleEntry for that agent, BEFORE the next agent is processed
      AND the broadcaster emits the rationale on the next 5Hz tick (no waiting for round end)
    - GIVEN a websocket client reconnects mid-round
      WHEN it receives its first snapshot
      THEN rationale_entries contains the existing window (not empty as it would with drain semantics)
    - GIVEN the RationalesContext frontend hook
      WHEN frame.rationales changes
      THEN useRationales() returns the new array directly (no accumulator, no dedup)
      AND the public hook contract { rationales: RationaleView[] } is unchanged
      AND the `RationalesProvider({ frame, children })` component signature is unchanged (App.tsx call-site stays as-is)
  </behavior>
  <action>
  **Step 1 — state.py: queue → deque.**

  In `src/alphaswarm/state.py`:
  - Replace `self._rationale_queue: asyncio.Queue[RationaleEntry]` (if that's the current name) with `self._rationale_window: deque[RationaleEntry] = deque(maxlen=50)`.
  - `push_rationale(entry)` → `self._rationale_window.append(entry)` (no async needed except for lock if other state ops use one; keep async signature to avoid caller churn).
  - REMOVE `drain_rationales(limit)`. Add `peek_rationales() -> tuple[RationaleEntry, ...]` returning `tuple(self._rationale_window)`.
  - `snapshot()` — ensure `StateSnapshot.rationale_entries` is set from `peek_rationales()` (or directly from the deque, frozen as tuple).

  **Step 2 — broadcaster.py: drop the drain.**

  In `src/alphaswarm/web/broadcaster.py:88-96` (verified line range from debug doc):
  ```python
  # BEFORE
  snap = state_store.snapshot()
  rationales = state_store.drain_rationales(5)
  d = dataclasses.asdict(snap)
  d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]

  # AFTER
  snap = state_store.snapshot()
  d = dataclasses.asdict(snap)
  # rationale_entries already populated from peek window — no override
  ```

  **Step 3 — batch_dispatcher.py: stream push_rationale.**

  In `src/alphaswarm/batch_dispatcher.py:_safe_agent_inference`. The function already streams `update_agent_state` after `worker.infer()` (per debug fix commit `1da741e`). Add a parallel `push_rationale` call:

  ```python
  async with agent_worker(persona, governor, client, model, state_store=state_store) as worker:
      decision = await worker.infer(...)
  if state_store is not None and decision.signal is not SignalType.PARSE_ERROR:
      await state_store.update_agent_state(persona["agent_id"], decision.signal, decision.confidence)
      # Determine current round. Read from state_store.snapshot().round_num if dispatcher doesn't already have it.
      current_round = state_store.snapshot().round_num   # if exposed; else accept round_num as a fn arg
      await state_store.push_rationale(RationaleEntry(
          agent_id=persona["agent_id"],
          signal=decision.signal,
          rationale=_sanitize_rationale(decision.rationale, max_len=50),
          round_num=current_round,
      ))
  return decision
  ```

  CRITICAL — verify the round_num source. Read the dispatcher function signature: does it accept `round_num`? If yes, use it directly (no snapshot lookup). If no, prefer adding it as a kwarg in the calling sequence (simulation.py:dispatch_wave already knows the round). Don't introduce a snapshot read inside the hot loop if it costs a lock.

  Inline a small `_sanitize_rationale(text: str, max_len: int) -> str` helper if one doesn't already exist in the module (strip newlines, truncate at max_len, append ellipsis if truncated). If a helper already exists in `worker.py` or elsewhere, import + reuse.

  **Step 4 — simulation.py: simplify or remove `_push_top_rationales`.**

  Read `src/alphaswarm/simulation.py` and locate `_push_top_rationales` calls (per debug doc: lines ~902-907, ~1043-1049, ~1172-1175). Since streaming now covers every agent in real time:
  - Option A (delete): remove all 3 calls + the method body.
  - Option B (defensive backstop): leave one call at end-of-round that re-pushes the top-N. But this DUPLICATES entries in the deque. Prefer Option A.

  Pick Option A. Document the removal in the commit body so future reviewers know it's intentional.

  **Step 5 — RationalesContext.tsx: simplify to one-line useMemo.**

  In `frontend/src/context/RationalesContext.tsx`. The current implementation has a useState accumulator + useEffect + dedup Set. Simplify ONLY the internals — the component signature `RationalesProvider({ frame, children }: { frame: StateFrame; children: ReactNode })` MUST be preserved (App.tsx:68 passes `<RationalesProvider frame={lastFrame}>`).

  Replace the body with the minimal version below. Keep the existing imports for `StateFrame` and `RationaleView` (and `ReactNode`); do NOT introduce a non-existent `useFrame` hook or `./FrameContext` module — neither exists in the codebase.

  ```tsx
  import { createContext, useContext, useMemo, type ReactNode } from 'react';
  import type { StateFrame } from '../adapter/frame';   // adjust path if different
  import type { RationaleView } from '../types';        // adjust path if different

  type RationalesCtxValue = { rationales: RationaleView[] };

  const Ctx = createContext<RationalesCtxValue>({ rationales: [] });

  export function RationalesProvider({
    frame,
    children,
  }: {
    frame: StateFrame;
    children: ReactNode;
  }) {
    const value = useMemo<RationalesCtxValue>(
      () => ({ rationales: frame.rationales ?? [] }),
      [frame.rationales],
    );
    return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
  }

  export function useRationales(): RationalesCtxValue {
    return useContext(Ctx);
  }
  ```

  Preserve the existing import paths for `StateFrame` and `RationaleView` from the current file (verify with `head -20 frontend/src/context/RationalesContext.tsx` before writing). The whole point is: drop the useState accumulator, useEffect, and dedup Set — back to one-line useMemo over `frame.rationales`. NO call-site changes in `App.tsx` — `App.tsx` is NOT in this task's files_modified.

  Public return shape: `{ rationales: RationaleView[] }` — UNCHANGED.
  Component prop signature: `{ frame: StateFrame; children: ReactNode }` — UNCHANGED.

  **Step 6 — Tests.**

  `tests/test_state.py`:
  - Replace `test_*drain_rationales*` with `test_rationale_window_appends_and_caps_at_50` and `test_rationale_window_peek_returns_full_window`.
  - Update `test_set_phase_*` if any test asserted queue clearing on round entry (window should NOT be cleared on round transition).

  `tests/test_batch_dispatcher.py`:
  - Add `test_safe_agent_inference_streams_rationale_push` — mock state_store, run _safe_agent_inference with a successful decision, assert push_rationale called once with sanitized rationale.
  - Add `test_safe_agent_inference_skips_rationale_on_parse_error` — same but with PARSE_ERROR; assert push_rationale NOT called.
  - Update the existing streaming-hook tests added in commit `1da741e` if they assume the old contract.

  Frontend: no new test required (RationalesContext has no unit test today). Build gate is enough.
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/test_state.py tests/test_batch_dispatcher.py -x -q && (compgen -G "tests/test_broadcaster*.py" > /dev/null && uv run pytest tests/test_broadcaster*.py -x -q || true) && cd frontend && npm run check && npm run build</automated>
  Live: trigger a sim, watch Rationale Feed populate progressively during R1 (1 → 100 entries spread over the round, not bulk-arrive at round end). After R3 complete, all ~30+ entries remain visible (no drain). Refresh the page mid-round — feed re-populates with the existing window from the WS snapshot.
  </verify>
  <done>
  - StateStore uses `deque(maxlen=50)` instead of asyncio.Queue for rationales.
  - batch_dispatcher streams push_rationale per-agent.
  - simulation.py `_push_top_rationales` removed (or no-op'd).
  - broadcaster no longer drains.
  - RationalesContext is back to ~one-line useMemo over `frame.rationales`. Component prop signature `{ frame: StateFrame; children: ReactNode }` UNCHANGED. App.tsx untouched.
  - All listed tests pass; useRationales() public contract unchanged.
  - Live: rationales appear progressively, survive reconnect.
  - Single atomic commit: `feat(state): rationale sliding window (closes mid-round-blackout + reconnect-data-loss)`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 5 [ITEM 5]: SignalWire live API audit</name>
  <files>src/alphaswarm/data_audit.py, src/alphaswarm/web/broadcaster.py, src/alphaswarm/state.py, frontend/src/components/v2.tsx, frontend/src/hooks/useDataSourceAudit.ts, frontend/src/adapter/frame.ts, tests/test_data_audit.py</files>
  <behavior>
    - GIVEN any data provider call (yfinance, FRED, RSS, etc.)
      WHEN it completes (success, error, or cached)
      THEN one audit entry `{ts, source, query, result, used}` is appended to a 100-entry deque
    - GIVEN an active simulation
      WHEN a WS snapshot is emitted
      THEN snap.data_source_audit carries the deque contents (as a list of dicts)
    - GIVEN the SignalWire component is mounted
      WHEN useDataSourceAudit() returns N entries
      THEN the ticker scrolls those N entries (oldest first → newest right)
      AND when N=0, the component renders a "WAITING FOR FIRST CALL…" placeholder
    - GIVEN production build
      WHEN `grep -r "SIGNAL_WIRE_SEED" dist/` runs
      THEN it returns 0 matches (no mock leak)
  </behavior>
  <action>
  **Step 1 — Backend audit collection.**

  Create `src/alphaswarm/data_audit.py`:
  ```python
  from __future__ import annotations
  from collections import deque
  from dataclasses import dataclass, field
  from typing import Any
  import time

  @dataclass(frozen=True)
  class DataSourceAuditEntry:
      ts: float
      source: str       # 'yfinance' | 'fred' | 'rss' | ...
      query: str        # human-readable: "AAPL 1d OHLCV" / "CPIAUCSL 1y"
      result: str       # 'ok' | 'cached' | 'error: <msg>' | '<n_bytes>'
      used: bool        # whether result fed into a worker prompt

  class DataSourceAuditBuffer:
      """Bounded audit log for data provider calls. Stored in app.state."""
      def __init__(self, max_entries: int = 100) -> None:
          self._buf: deque[DataSourceAuditEntry] = deque(maxlen=max_entries)

      def record(self, source: str, query: str, result: str, used: bool = False) -> None:
          self._buf.append(DataSourceAuditEntry(
              ts=time.time(), source=source, query=query, result=result, used=used,
          ))

      def snapshot(self) -> tuple[DataSourceAuditEntry, ...]:
          return tuple(self._buf)
  ```

  **Step 2 — Wire it into StateStore so it surfaces in snapshots.**

  Two options:
  - (A) Add `_audit_buffer: DataSourceAuditBuffer` to `StateStore` and expose `record_data_source(...)` + `peek_data_source_audit()`. Add `data_source_audit: tuple[dict, ...]` to `StateSnapshot`. Most consistent with the rest of the wire path.
  - (B) Park it on `app.state.data_source_audit_buffer` and inject it into snapshots via broadcaster.

  Pick (A) for symmetry with rationale_entries. Update `state.py` accordingly. Update broadcaster.py to no-op (asdict picks it up automatically — same pattern as rationale_entries post-Task-4 cleanup).

  **Step 3 — Instrument data providers.**

  Grep for provider call sites:
  ```bash
  grep -rE "yfinance|yahoo|fred|rss" src/alphaswarm/ --include "*.py" -l
  ```

  In each provider module (likely `src/alphaswarm/providers/*.py` or similar — locate via grep), after each fetch call, do:
  ```python
  state_store.record_data_source(
      source='yfinance',
      query=f"{ticker} {period} OHLCV",
      result='ok' if response else 'error: empty',
      used=True,  # set False if cached or unused
  )
  ```

  If state_store isn't already threaded into provider modules, thread it via constructor injection or module-level setter. Keep changes minimal — one record call per top-level fetch.

  IMPORTANT: Do NOT block the event loop. record() is sync + bounded; safe to call from async context.

  **Step 4 — Frontend hook + consumer swap.**

  Create `frontend/src/hooks/useDataSourceAudit.ts`:
  ```ts
  import { useMemo } from 'react';
  import { useTelemetry } from '../context/TelemetryContext';   // or wherever
  import type { DataSourceAuditEntry } from '../types';

  /**
   * Returns the latest data-source audit entries from the WS frame.
   * Returns [] when sim has not made any provider calls yet.
   */
  export function useDataSourceAudit(): DataSourceAuditEntry[] {
    const telemetry = useTelemetry();
    return useMemo(() => telemetry.dataSourceAudit ?? [], [telemetry.dataSourceAudit]);
  }
  ```

  Update `frontend/src/types/index.ts` (or wherever shared types live) to declare `DataSourceAuditEntry` + extend `Telemetry` with `dataSourceAudit?: DataSourceAuditEntry[]`.

  Update `frontend/src/adapter/frame.ts` to copy `r.data_source_audit` (snake_case wire) → `telemetry.dataSourceAudit` (camelCase frontend), with `?? []` fallback.

  In `frontend/src/components/v2.tsx`, find the SignalWire component and the DataSourcesTakeover. SignalWire current behavior (per KR-41.6-14): DEV-only dynamic import of `mocks/wire.ts` for SIGNAL_WIRE_SEED.

  REPLACE the consumer with:
  ```tsx
  const audit = useDataSourceAudit();
  // remove: const [signalWireSeed, setSignalWireSeed] = useState<...>([]);
  // remove: useEffect(() => { if (import.meta.env.DEV) import('../mocks/wire').then(...) }, []);
  // Use `audit` for render. If audit.length === 0, render "WAITING FOR FIRST CALL…" placeholder.
  ```

  Same swap for DataSourcesTakeover — point its stats grid at `useDataSourceAudit()` aggregation (group by source, count by used vs unused, count by result type).

  KR-41.6-14 stays valid: `mocks/wire.ts` and `mocks/sources.ts` files stay on disk as DEV fallback (do NOT delete) — only the CONSUMER swaps from mock to live. The dynamic import code path is REPLACED by the hook call, so the dynamic import statement is removed from production bundle.

  **Step 5 — Production grep gate.**

  ```bash
  cd frontend && npm run build
  grep -r "SIGNAL_WIRE_SEED" dist/ ; echo "exit $?"   # must exit 1 (no match)
  grep -r "mocks/wire" dist/assets/ ; echo "exit $?"  # must exit 1
  grep -r "mocks/sources" dist/assets/ ; echo "exit $?"  # must exit 1
  ```

  **Step 6 — Tests.**

  Backend: add `tests/test_data_audit.py` asserting:
  - `DataSourceAuditBuffer.record()` appends entries.
  - Buffer caps at max_entries (test with maxlen=3, push 5, assert tuple length == 3 and last 3 entries kept).
  - `snapshot()` returns a tuple of `DataSourceAuditEntry` instances in insertion order.
  - StateStore integration: `record_data_source(...)` → `snapshot()['data_source_audit']` carries entries via `dataclasses.asdict` serialization.

  Frontend: no new test required (manual UAT covers).
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/test_data_audit.py tests/test_state.py -x -q && cd frontend && npm run check && npm run build && ! grep -r "SIGNAL_WIRE_SEED" dist/ && ! grep -r "mocks/wire" dist/assets/ && ! grep -r "mocks/sources" dist/assets/</automated>
  Live: trigger a sim, observe SignalWire ticker shows real yfinance/FRED/RSS calls scrolling (not the mock seed). Open DataSourcesTakeover — stats reflect actual call counts.
  </verify>
  <done>
  - `src/alphaswarm/data_audit.py` exists with `DataSourceAuditEntry` + `DataSourceAuditBuffer`.
  - `tests/test_data_audit.py` exists and passes (record + cap + snapshot + state-integration).
  - StateStore exposes record_data_source + snapshot carries data_source_audit.
  - At least 2 data provider modules instrumented (yfinance + one other).
  - `useDataSourceAudit()` hook exists.
  - SignalWire consumer swapped from mock to hook; DataSourcesTakeover same.
  - Production grep gates all clean: SIGNAL_WIRE_SEED / mocks/wire / mocks/sources all 0 hits in dist/.
  - Mock files stay on disk (KR-41.6-14 valid).
  - Tests + build green.
  - Single atomic commit: `feat(data): live SignalWire audit (replaces DEV mock seed; mocks stay as DEV fallback)`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 6 [ITEM 6]: Advisory items[] + sector enrichment + frontend fallback (closes task #10)</name>
  <files>src/alphaswarm/advisory/prompt.py, src/alphaswarm/advisory/sector_map.py, src/alphaswarm/advisory/engine.py, src/alphaswarm/advisory/types.py, frontend/src/components/v2.tsx, tests/test_advisory_synthesize.py</files>
  <behavior>
    - GIVEN a portfolio with 32 unique ticker holdings (user's Schwab + Roth — Roth duplicates of MRVL/QQQ count toward the same ticker entry)
      WHEN the orchestrator synthesizes an advisory report
      THEN report.items contains one entry per UNIQUE holding (len(items) == 32)
      AND each item has consensus_signal + confidence (HOLD@0.2-0.4 as placeholder for low-conviction holdings)
      AND affected_holdings counts items where consensus_signal != HOLD OR confidence > 0.4
    - GIVEN a holding with a known ticker (e.g., AAPL)
      WHEN sector enrichment runs
      THEN the holding dict gains sector, region_exposure, supply_chain_sensitivity, macro_beta fields
      AND items are sorted by relevance_score (entity_impact × macro_beta × seed match)
      AND top-15 holdings carry full enrichment; the rest carry sector tag only
    - GIVEN an UNKNOWN ticker
      WHEN sector map lookup runs
      THEN it returns the UNKNOWN default {sector: 'unknown', region_exposure: 'global', supply_chain_sensitivity: 'med', macro_beta: 0.0}
    - GIVEN AdvisoryV2 receives report.items.length === 0 but cycleId + report exist
      WHEN the modal renders
      THEN SWARM VIEW tile is derived from bracket_summary
      AND Holdings tab shows one HOLD-placeholder card per holding (full 32-unique-ticker view)
      AND Overview narrative renders regardless of items emptiness
  </behavior>
  <action>
  **Step 1 — Sector map.**

  Create `src/alphaswarm/advisory/sector_map.py`:
  ```python
  """Curated ticker → sector enrichment map.

  Covers the user's 32 unique tickers (Schwab + Roth holdings — Roth MRVL/QQQ
  duplicates count toward the same SECTOR_MAP entry as the corresponding Schwab
  position). UNKNOWN tickers fall back to a global-neutral default.

  Used by advisory.engine to inform relevance scoring before prompt synthesis.
  """
  from typing import TypedDict, Literal

  RegionExposure = Literal['US', 'Asia', 'global', 'EM', 'cash']
  Sensitivity = Literal['low', 'med', 'high']

  class SectorInfo(TypedDict):
      sector: str
      region_exposure: RegionExposure
      supply_chain_sensitivity: Sensitivity
      macro_beta: float   # [-1.0, 1.0]

  SECTOR_MAP: dict[str, SectorInfo] = {
      'AAPL': {'sector': 'consumer_tech', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.85},
      'AMZN': {'sector': 'ecommerce_cloud', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.95},
      'ARM':  {'sector': 'semis_ip', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 1.0},
      'ASML': {'sector': 'semis_litho', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 1.0},
      'AVGO': {'sector': 'semis_networking', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.95},
      'BYDDY': {'sector': 'auto_ev', 'region_exposure': 'Asia', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.8},
      'COHR': {'sector': 'photonics', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.85},
      'CHAT': {'sector': 'ai_etf', 'region_exposure': 'global', 'supply_chain_sensitivity': 'med', 'macro_beta': 0.9},
      'CQQQ': {'sector': 'china_tech_etf', 'region_exposure': 'Asia', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.85},
      'CRDO': {'sector': 'semis_networking', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.95},
      'DBX':  {'sector': 'saas', 'region_exposure': 'US', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.6},
      'HIMS': {'sector': 'consumer_health', 'region_exposure': 'US', 'supply_chain_sensitivity': 'med', 'macro_beta': 0.55},
      'HON':  {'sector': 'industrials', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.7},
      'ISRG': {'sector': 'medtech', 'region_exposure': 'global', 'supply_chain_sensitivity': 'med', 'macro_beta': 0.75},
      'LPL':  {'sector': 'displays', 'region_exposure': 'Asia', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.6},
      'MRVL': {'sector': 'semis_networking', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.95},
      'NIO':  {'sector': 'auto_ev', 'region_exposure': 'Asia', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.85},
      'NKE':  {'sector': 'consumer_apparel', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.6},
      'NVDA': {'sector': 'semis_ai_accel', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 1.0},
      'PLTR': {'sector': 'enterprise_ai', 'region_exposure': 'global', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.85},
      'PYPL': {'sector': 'fintech', 'region_exposure': 'global', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.7},
      'QQQ':  {'sector': 'large_cap_tech_etf', 'region_exposure': 'US', 'supply_chain_sensitivity': 'med', 'macro_beta': 0.9},
      'SCHW': {'sector': 'brokerage', 'region_exposure': 'US', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.75},
      'SOFI': {'sector': 'fintech', 'region_exposure': 'US', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.8},
      'SPY':  {'sector': 'broad_market_etf', 'region_exposure': 'US', 'supply_chain_sensitivity': 'med', 'macro_beta': 1.0},
      'SWYXX': {'sector': 'money_market', 'region_exposure': 'cash', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.0},
      'TLN':  {'sector': 'utilities_nuclear', 'region_exposure': 'US', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.4},
      'TSLA': {'sector': 'auto_ev', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.9},
      'TSM':  {'sector': 'semis_foundry', 'region_exposure': 'Asia', 'supply_chain_sensitivity': 'high', 'macro_beta': 1.0},
      'VRT':  {'sector': 'datacenter_infra', 'region_exposure': 'global', 'supply_chain_sensitivity': 'high', 'macro_beta': 0.9},
      'VST':  {'sector': 'utilities_power', 'region_exposure': 'US', 'supply_chain_sensitivity': 'low', 'macro_beta': 0.45},
      'WTAI': {'sector': 'ai_etf', 'region_exposure': 'global', 'supply_chain_sensitivity': 'med', 'macro_beta': 0.9},
  }

  UNKNOWN_SECTOR: SectorInfo = {
      'sector': 'unknown',
      'region_exposure': 'global',
      'supply_chain_sensitivity': 'med',
      'macro_beta': 0.0,
  }

  def lookup(ticker: str) -> SectorInfo:
      return SECTOR_MAP.get(ticker.upper(), UNKNOWN_SECTOR)
  ```

  Coverage note: this dict has 32 entries — one per UNIQUE ticker in the user's holdings. The user's raw position list contains 34 lines because MRVL and QQQ appear twice (Schwab + Roth IRA), but those duplicates resolve to the same ticker entry. The test assertion in Step 6 verifies 32 unique tickers.

  **Step 2 — Prompt rewrite.**

  In `src/alphaswarm/advisory/prompt.py`, find the section that instructs the LLM about items[]. Replace the current "MUST be OMITTED from items" instruction with:

  > "Produce one item per holding in the portfolio. NEVER OMIT a holding. For holdings without a clear directional signal, use consensus_signal='HOLD' with confidence in the range 0.20–0.40 as a placeholder. The user wants to see their FULL portfolio context — every holding gets an item, even if the signal is weak. Strong-conviction items still drive the headline narrative.
  >
  > `affected_holdings` is the COUNT of items where consensus_signal is not 'HOLD' OR confidence > 0.4. This represents items with a directional or high-conviction view, distinct from total items count."

  Update any docstring / schema comment that documented the old "omit" behavior.

  **Step 3 — Engine enrichment + relevance scoring.**

  In `src/alphaswarm/advisory/engine.py`:
  ```python
  from .sector_map import lookup as sector_lookup

  def _enrich_holdings(holdings: list[dict], entity_impacts: dict[str, float], seed_text: str) -> list[dict]:
      """Adds sector_map fields + relevance_score to each holding; returns sorted DESC by relevance."""
      seed_lower = seed_text.lower()
      enriched: list[dict] = []
      for h in holdings:
          ticker = h.get('ticker', '').upper()
          sm = sector_lookup(ticker)
          entity_impact = float(entity_impacts.get(ticker, 0.0))
          seed_match = 1.0 if ticker.lower() in seed_lower or sm['sector'] in seed_lower else 0.0
          relevance = abs(entity_impact) * abs(sm['macro_beta']) + 0.5 * seed_match
          enriched.append({**h, **sm, 'relevance_score': relevance})
      enriched.sort(key=lambda x: x['relevance_score'], reverse=True)
      return enriched

  # Where build_prompt is called:
  enriched = _enrich_holdings(holdings, entity_impacts, seed_text)
  top_15 = enriched[:15]
  rest = [{'ticker': h['ticker'], 'sector': h['sector']} for h in enriched[15:]]
  prompt = build_prompt(top_holdings=top_15, rest_holdings=rest, ...)
  ```

  Update `build_prompt` signature in `prompt.py` to accept `top_holdings: list[dict]` and `rest_holdings: list[dict]`. Format them differently in the prompt body (top-15 with full enrichment, rest with sector tag only).

  **Step 4 — Types.**

  In `src/alphaswarm/advisory/types.py`, update `affected_holdings` docstring / field semantics if the type asserts a constraint. No structural change needed.

  **Step 5 — Frontend graceful fallback.**

  In `frontend/src/components/v2.tsx` AdvisoryV2 component, when rendering:
  ```tsx
  // When report.items.length === 0 but cycleId + report exist:
  const items = report.items;
  const hasItems = items.length > 0;

  // Overview tab:
  //  - SWARM VIEW tile: if hasItems → compute from items; ELSE derive dominant signal from bracket_summary
  //  - HOLDINGS AFFECTED tile: hasItems ? affected_holdings_count : 0
  //  - Narrative: render report.narrative regardless

  // Holdings tab:
  //  - If hasItems → render real items
  //  - ELSE render one HOLD-placeholder card per holding from portfolio.holdings:
  //    items = portfolio.holdings.map(h => ({
  //      ticker: h.ticker,
  //      consensus_signal: 'HOLD',
  //      confidence: 0.3,
  //      narrative: '(no specific signal — full portfolio view)',
  //      placeholder: true,
  //    }))
  //    Render with reduced opacity (e.g., var(--text-3)) to differentiate from real items
  ```

  Implementation detail: portfolio holdings ARE accessible from the cycle metadata or from the report's `portfolio_outlook` field (per Phase 41.4 + quick task 260507-19f schema). If holdings aren't on the report payload, derive from the cycle's seed_pipeline metadata or from `bracket_summary` (less ideal — list of bracket KEYS, not holdings). PREFER report.portfolio.holdings; if absent, log a warn and render the items as-is (which is the empty-state we already document).

  **Step 6 — Regression test `tests/test_advisory_synthesize.py`.**

  ```python
  import pytest
  from unittest.mock import AsyncMock, patch
  from alphaswarm.advisory import engine
  from alphaswarm.advisory.sector_map import lookup, SECTOR_MAP, UNKNOWN_SECTOR

  def test_sector_map_covers_user_tickers():
      """All 32 unique user tickers must have a sector entry."""
      required = ['AAPL','AMZN','ARM','ASML','AVGO','BYDDY','COHR','CHAT','CQQQ','CRDO',
                  'DBX','HIMS','HON','ISRG','LPL','MRVL','NIO','NKE','NVDA','PLTR',
                  'PYPL','QQQ','SCHW','SOFI','SPY','SWYXX','TLN','TSLA','TSM','VRT',
                  'VST','WTAI']
      assert len(required) == 32, f"required list must have 32 unique tickers, got {len(required)}"
      for t in required:
          assert t in SECTOR_MAP, f"missing sector entry: {t}"
          info = SECTOR_MAP[t]
          assert -1.0 <= info['macro_beta'] <= 1.0
          assert info['region_exposure'] in ('US','Asia','global','EM','cash')
          assert info['supply_chain_sensitivity'] in ('low','med','high')

  def test_sector_map_unknown_default():
      assert lookup('NOTREAL') == UNKNOWN_SECTOR
      assert lookup('NOTREAL')['sector'] == 'unknown'
      assert lookup('NOTREAL')['macro_beta'] == 0.0

  def test_enrich_holdings_sorts_by_relevance():
      """Higher entity_impact + macro_beta should sort first."""
      holdings = [
          {'ticker': 'SWYXX'},   # macro_beta 0.0 → low relevance
          {'ticker': 'NVDA'},    # macro_beta 1.0 + AI seed match
      ]
      entity_impacts = {'NVDA': 0.9, 'SWYXX': 0.1}
      seed = "AI chip export controls"
      enriched = engine._enrich_holdings(holdings, entity_impacts, seed)
      assert enriched[0]['ticker'] == 'NVDA'
      assert enriched[-1]['ticker'] == 'SWYXX'
      assert 'sector' in enriched[0]
      assert 'macro_beta' in enriched[0]

  def test_prompt_instructs_never_omit():
      """Prompt MUST contain the 'NEVER OMIT' or equivalent one-item-per-holding directive."""
      from alphaswarm.advisory.prompt import build_prompt
      top = [{'ticker': 'AAPL', 'sector': 'consumer_tech', 'macro_beta': 0.85}]
      rest = []
      p = build_prompt(top_holdings=top, rest_holdings=rest, seed_text="test", entity_impacts={}, bracket_summary=[])  # signature may differ — adjust
      assert "NEVER OMIT" in p or "one item per holding" in p.lower()
  ```

  Unit test asserts prompt instructions + enrichment + sector map shape. Integration with real LLM is deferred — too expensive to gate. Document this in commit body.
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/test_advisory* -x -q && cd frontend && npm run check && npm run build</automated>
  Live: with backend running, re-trigger advisory on cycle 7ab3984d-... via `curl -X POST http://localhost:8000/api/advisory/7ab3984d-36a5-4d6a-9178-bfaa842b15d2` (orchestrator regenerates; ~3-5 min wait). Poll `curl http://localhost:8000/api/advisory/7ab3984d-36a5-4d6a-9178-bfaa842b15d2` until 200; assert `jq '.items | length'` returns the holding count (32 unique or whatever the portfolio has). In the UI, open AdvisoryV2 modal → Overview tile shows real numbers, Holdings tab shows full portfolio with real signals (no placeholders if the prompt rewrite succeeded).
  </verify>
  <done>
  - `src/alphaswarm/advisory/sector_map.py` exists with 32 ticker entries (one per unique user holding) + UNKNOWN default.
  - `prompt.py` instructs "one item per holding, never omit; HOLD@0.2-0.4 placeholder".
  - `engine.py` enriches + sorts by relevance; passes top-15 + rest to prompt.
  - Frontend AdvisoryV2 gracefully falls back to bracket-derived SWARM tile + per-holding placeholder cards when items=[].
  - `tests/test_advisory_synthesize.py` passes (32-ticker sector map coverage + enrichment + prompt instructions).
  - Build gates green (backend + frontend).
  - Live re-trigger: items non-empty, Holdings tab shows full portfolio.
  - Single atomic commit: `feat(advisory): one-item-per-holding + sector enrichment + UI fallback (closes task #10)`
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| frontend → backend HTTP | All `/api/*` requests; untrusted client input (cycle_id, round number, ticker strings) |
| backend → Neo4j Cypher | Cycle IDs from clients flow into MATCH ... WHERE r.cycle_id = $cycle_id |
| backend → Ollama | Worker/orchestrator prompts include seed_text + portfolio CSV |
| WS broadcaster → clients | Per-client queue with drop-oldest backpressure; new fields (data_source_audit, governor.current_slots, etc.) MUST NOT carry secrets |
| data providers → app.state | yfinance/FRED/RSS responses flow into audit buffer (query/result strings) — could be large |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-260512-jqn-01 | Tampering | /api/edges (ITEM 2) — cycle_id from URL flows into Cypher | mitigate | Use Cypher parameters (`$cycle_id`, `$round`) — NEVER string-format into the query. The route already runs under FastAPI path validation; round must coerce to int (`Query(..., ge=1, le=3)`). |
| T-260512-jqn-02 | Information Disclosure | /api/edges response leaks agent IDs across cycles | accept | Agent IDs (Q-01, M-05 etc.) are not sensitive in this single-user local-only product. Cycle isolation is enforced by the cycle_id filter. |
| T-260512-jqn-03 | Information Disclosure | data_source_audit WS field (ITEM 5) might leak API keys in `result` strings | mitigate | DataSourceAuditBuffer.record() takes only `result: str` summary ('ok' / 'cached' / 'error: <msg>'). Provider modules MUST NEVER pass raw response bodies or env-vars as `result`. Add unit test asserting record() rejects strings containing 'sk-' or 'API_KEY=' prefixes (defensive). |
| T-260512-jqn-04 | Denial of Service | rationale_window deque (ITEM 4) unbounded growth | mitigate | `deque(maxlen=50)` cap enforced at the data structure level — append silently drops oldest. data_source_audit_buffer same pattern (maxlen=100). |
| T-260512-jqn-05 | Denial of Service | data_source audit records called from sync provider context | mitigate | record() is O(1) deque.append — no I/O, no lock contention. Safe to call from any context. Verified by reading the implementation. |
| T-260512-jqn-06 | Tampering | Sector map (ITEM 6) — UNKNOWN ticker fallback | accept | UNKNOWN_SECTOR returns global-neutral defaults; cannot be exploited because there's no client input path that injects tickers — tickers come from the user's Schwab CSV (in-memory, never persisted per project decisions). |
| T-260512-jqn-07 | Information Disclosure | Advisory prompt (ITEM 6) sends portfolio holdings + seed text to local Ollama | accept | Ollama is local-only per CLAUDE.md hard constraint #2 (no cloud APIs). Portfolio data never leaves localhost. |
| T-260512-jqn-08 | Spoofing | Onboarding /api/health gate (ITEM 1 indirect — CSS support) | accept | Local-only; no network spoofing risk. The CSS work itself adds no attack surface. |
| T-260512-jqn-09 | Repudiation | data_source_audit lacks persistence (ITEM 5) | accept | Audit is volatile/in-memory by design — debug/observability tool, not a compliance trail. Documented in module docstring. |
| T-260512-jqn-10 | Elevation of Privilege | New CSS rules (ITEM 1) injecting via `style` attribute | accept | All CSS is static in styles.css — no `dangerouslySetInnerHTML`, no dynamic style construction from user input. |
</threat_model>

<verification>
**Per-task verification** is defined inline in each `<verify>` block. **Phase-level verification:**

1. Full backend test suite for touched modules:
   ```bash
   cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm"
   uv run pytest tests/test_state.py tests/test_batch_dispatcher.py tests/test_edges_route.py tests/test_data_audit.py tests/test_advisory* -x -q
   ```
2. Frontend build + check + grep gates:
   ```bash
   cd frontend && npm run check && npm run build
   ! grep -r "SIGNAL_WIRE_SEED" dist/
   ! grep -r "mocks/wire" dist/assets/
   ! grep -r "mocks/sources" dist/assets/
   ! grep -rE "window\.(AS_DATA|Icon)" src/
   ```
3. Live end-to-end smoke (manual UAT after all 6 commits):
   - Clear localStorage `as_onboarding_v1_complete`; reload → Onboarding renders properly styled.
   - Run sim with a real seed.
   - During R1: Rationale Feed populates progressively (1 → 100 entries spread over the round window). PARALLEL SLOTS shows live numerator. SignalWire ticker shows real provider calls (NOT mock seed text).
   - Click any agent dot → InterviewV2 renders as full-screen modal (header + 2-column body + tabs).
   - Click any bracket row → BracketDeepDive renders with member list + stats panel.
   - After R3 complete: `/api/edges/{cycle_id}?round=3` returns > 0 edges. AdvisoryV2 opens, Holdings tab shows full portfolio (32 unique tickers).
</verification>

<success_criteria>
ALL of:
1. 6 atomic git commits land on master (or branch — user's call), one per ITEM.
2. Every per-task `<verify>` automated command exits 0.
3. Production grep gates clean (no SIGNAL_WIRE_SEED / mocks/wire / mocks/sources / window.AS_DATA / window.Icon).
4. Live UAT (manual): every observable truth in `must_haves.truths` is observed by the user.
5. CONTRACT.md §2.1 frontend hook return shapes unchanged (`useAgents`, `useBrackets`, `useTelemetry`, `useRationales`, `useCurrentCycle` all behave the same to callers).
6. `RationalesProvider({ frame, children })` component prop signature unchanged — App.tsx untouched.
7. KR-41.1-05 (governor slot stub) is fully closed. KR-41.6-14 (DEV-only mock dynamic import) stays valid (mock files still on disk; only SignalWire consumer swapped).
8. No regression in pre-existing 911-passing test suite (debug-doc baseline).
</success_criteria>

<output>
After completion, create `.planning/quick/260512-jqn-address-6-post-run-follow-ups-interviewv/260512-jqn-SUMMARY.md` with per-ITEM result + commit SHAs + UAT observations.
</output>
