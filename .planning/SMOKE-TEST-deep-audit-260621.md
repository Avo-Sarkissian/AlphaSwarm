# Smoke test — deep-audit fixes (branch `fix/deep-audit-260621`, PR #2)

Goal: confirm the audit fixes work on **real data** (Neo4j + live inference), since
unit tests can't exercise the actual report text or the live WS/graph. ~1 cycle.

> Tip: set `ALPHASWARM_NUM_ROUNDS=2` for a faster smoke (still exercises every
> fix except the round-3-specific paths). Use a rumor that names a **held**
> company so the advisory/entity paths light up, e.g. **NVIDIA**.

---

## 0. Prerequisites

- [ ] Neo4j up: `docker compose up -d` → wait for healthy (`docker compose ps`)
- [ ] Inference backend up (per your model decision): MLX/Ollama serving the
      configured worker + orchestrator models; `ollama ps` or your MLX server responds
- [ ] On the branch: `git switch fix/deep-audit-260621`
- [ ] Deps current: `uv sync`

---

## 1. CLI path — run a cycle, then generate the report

```bash
uv run python -m alphaswarm run "NVIDIA reportedly cut Q3 datacenter GPU orders amid soft demand"
uv run python -m alphaswarm report          # defaults to most recent cycle
```

Check the printed/`reports/` output:

- [ ] **F-06** — the report contains BOTH a **global BUY/SELL/HOLD consensus**
      section AND a **signal-flip analysis** section (previously silently missing;
      the ReAct loop no longer logs `Unknown tool 'consensus_summary'`/`'signal_flips'`).
- [ ] **F-01** — "Key dissenters" lists a genuine **minority** (a handful), NOT all
      ~100 agents.
- [ ] **F-02** — signal-flips lists only agents that **actually changed** between
      rounds (no-change agents excluded), and each row has a real round number
      (not blank/NULL).
- [ ] **F-03** — if a shock was injected, per-bracket shock impact shows non-zero
      BUY/SELL percentages and ▲/▼ arrows (not all `0% / HOLD / ·`).
- [ ] **F-09** — `r{1,2,3}_parse_errors` in the cycle metrics are low/expected;
      no agent silently dropped for a `}` in its rationale.

---

## 2. Advisory path — entity ranking (F-07)

```bash
# Advisory runs from the web UI (Advisory tab) or its route after a cycle.
```

- [ ] **F-07** — with a rumor naming a held company (NVIDIA→NVDA, "Taiwan
      Semiconductor"→TSM), that holding ranks **near the top** of the advisory /
      conviction set — not buried. (Pre-fix: ranking was inert.)
- [ ] **F-28** — a rumor with an incidental sector word ("the chart **displays** a
      breakout") does NOT pull an unrelated holding (LPL) into the top set.

---

## 3. Web path — live graph, replay, settings

```bash
./start            # or: uv run python -m alphaswarm web   → http://127.0.0.1:8000
```

Start a run from the UI and watch:

- [ ] **F-08** — the agent graph / peer influence looks **diverse** across brackets
      through Round 2 (not every agent converging on one bloc).
- [ ] **F-24** — frames keep streaming the instant a **replay** starts (no gap /
      no broadcaster errors in the server log during replay start-up).
- [ ] **F-12** — for a **2-round** cycle, replay **Forward stops at round 2**
      (never advances to an empty round-3 / 0-agent graph).
- [ ] **F-35** — "Top Influencers (out-degree)" shows only real edge sources
      (no `0` filler rows).
- [ ] **F-16** — on a slow advisory poll, no stacked/overlapping requests in the
      browser Network tab (at most one in flight).
- [ ] **F-33** — double-clicking **Run** starts the sim **once** (no duplicate
      start / 409 console error).
- [ ] **F-13** (settings) — store a cloud key under one provider, then apply a
      **different** provider preset without entering a key → the new provider's
      key is **empty**, not the old vendor's secret. (`GET /api/settings` shows it masked/unset.)

---

## 4. Fast sanity (no services needed)

- [ ] `uv run pytest -q` → 1269 passed, 0 failed
- [ ] `cd frontend && npx vitest run` → 96 passed
- [ ] `lint-imports` → 1 kept, 0 broken

---

### Notes
- F-04/F-17/F-21 (governor/memory) only manifest under real memory pressure —
  covered by unit tests; no smoke step needed.
- F-05/F-10/F-11/F-18/F-22/F-23 are cloud-provider paths — exercise only if you
  run with a cloud provider configured (otherwise local Ollama path is unaffected).
- Pre-existing `_handle_inject "never awaited"` warning is unrelated to this branch.
