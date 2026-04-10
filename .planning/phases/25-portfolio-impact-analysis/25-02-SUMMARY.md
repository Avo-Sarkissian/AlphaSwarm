---
phase: 25-portfolio-impact-analysis
plan: 02
subsystem: portfolio
tags: [portfolio, cli, argparse, jinja2, react, html, deterministic, fail-fast]

# Dependency graph
requires:
  - phase: 25-portfolio-impact-analysis
    plan: 01
    provides: portfolio.py (parse_schwab_csv_async, build_portfolio_impact, TICKER_ENTITY_MAP, TypedDicts, PortfolioParseError), 10_portfolio_impact.j2 markdown template, static TOOL_TO_TEMPLATE/SECTION_ORDER registration
  - phase: 15-post-simulation-report
    provides: ReportEngine ReACT loop, ReportAssembler, ToolObservation
  - phase: 24-html-report-export
    provides: assemble_html Jinja environment with autoescape=True, report.html.j2 base template
provides:
  - src/alphaswarm/cli.py::_handle_report — --portfolio CLI flag wiring with deterministic pre-call, fail-fast validation, privacy-safe logging, idempotent tool closure
  - src/alphaswarm/report.py::build_react_system_prompt — dynamic system prompt builder with optional portfolio mandate + CONTEXT AWARENESS clause
  - src/alphaswarm/report.py::ReportEngine — new system_prompt and pre_seeded_observations kwargs; run() injects pre-seeded observations into LLM conversation messages BEFORE first chat() call
  - src/alphaswarm/templates/report/report.html.j2 — Portfolio Impact Matched Positions + Coverage Gaps section cards (Jinja autoescape, no new CSS)
  - tests/test_portfolio_integration.py — 39 integration tests covering prompt builder, pre-seeded observations, CLI flag, fail-fast matrix, HTML rendering, determinism
affects:
  - End-to-end portfolio report UX: `alphaswarm report --portfolio <csv>` deterministically renders Portfolio Impact in markdown + HTML even if the ReACT LLM ignores the tool
  - Future report phases consuming pre_seeded_observations pattern
  - Future phases needing dynamic ReACT system prompts

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composable system prompt builder: single build_react_system_prompt(*, include_portfolio=False) replaces hard-coded REACT_SYSTEM_PROMPT constant (kept for backwards compat)"
    - "Deterministic pre-call via pre_seeded_observations: pre-compute authoritative data in the CLI handler, wrap in ToolObservation, inject into ReportEngine; the engine both returns it from run() AND injects it into the LLM's messages list as a user-role 'OBSERVATION:' payload BEFORE the first chat() call so the model synthesizes narrative from context rather than fetching"
    - "Idempotent tool closure: even though data is pre-computed, register an async closure that always returns the same PortfolioImpact so if the ReACT LLM does call the tool, the re-call is a safe no-op"
    - "Fail-fast matrix for explicit user input: missing path / not regular file / malformed CSV / zero equity rows all raise SystemExit(2) with single-line stderr errors — explicit flag must never silently succeed with empty data"
    - "Privacy-safe structlog keys: emit only path + counts + error class name; never ticker symbols, names, or currency values"
    - "Static vs runtime tool registration split: TOOL_TO_TEMPLATE/SECTION_ORDER live in report.py unconditionally (Plan 01); the runtime tools dict entry is conditional on --portfolio in cli.py (Plan 02). The two layers address different concerns — template routing happens at assembly time regardless of whether the tool runs, while tool registration happens at engine-construction time only when the user opts in."
    - "De-dup at run() return: pre-seeded observations are authoritative, so if the ReACT loop happens to call a pre-seeded tool, the loop result is dropped in favor of the pre-seeded entry"

key-files:
  created:
    - .planning/phases/25-portfolio-impact-analysis/25-02-SUMMARY.md
  modified:
    - src/alphaswarm/report.py (+95/-5 lines — refactor prompt, ReportEngine kwargs, run() injection + de-dup)
    - src/alphaswarm/cli.py (+143/-2 lines — imports, portfolio pre-call block, --portfolio argparse, dispatcher wiring)
    - src/alphaswarm/templates/report/report.html.j2 (+76 lines — two Portfolio Impact section cards)
    - tests/test_portfolio_integration.py (+916 lines — 39 tests across 6 classes + 9 module-level async tests)
    - .gitignore (+1 line — .alphaswarm/ runtime sentinel directory)

key-decisions:
  - "Pre-seeded observations MUST be injected into the LLM's messages list (not just the observations return value) — otherwise the LLM has no context to synthesize a narrative and will either try to call the tool or claim the data is missing. Implemented as a loop right after the initial messages array is built, before the first chat() call."
  - "REACT_SYSTEM_PROMPT kept as a module-level constant equal to build_react_system_prompt() with default kwargs, preserving all existing test_report.py imports without modification."
  - "Monkeypatch strategy for _handle_report: patch alphaswarm.app.create_app_state (where it is defined) rather than alphaswarm.cli.create_app_state (where it is locally imported inside the function body). The plan's literal monkeypatch code would have failed because the symbol does not exist as a module-level attribute of cli.py; the substantive intent (stub out the real AppState) is preserved via the _patch_app_factory helper."
  - "_portfolio_impact_tool closure captures the pre-computed result via closure rather than reading it from engine state, ensuring call-count-independent idempotency and avoiding any possibility of state drift between the pre-seeded observation and a potential LLM re-call."
  - ".alphaswarm/ sentinel directory added to .gitignore as housekeeping: write_sentinel() writes it relative to cwd and the privacy-logging test triggered its creation. Pre-existing runtime output pattern that had not been gitignored; now cleaned up."

requirements-completed: [PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04]

# Metrics
duration: ~22m
completed: 2026-04-10
---

# Phase 25 Plan 02: Portfolio CLI Wiring and HTML Render Summary

**Wires `--portfolio` into `alphaswarm report` with deterministic pre-call delivery — parses the Schwab CSV, pre-computes a `PortfolioImpact`, injects it as a pre-seeded `ToolObservation` into both `ReportEngine`'s result list AND the LLM's conversation context, registers an idempotent tool closure for ReACT re-calls, and renders two new HTML section cards — with 39 integration tests locking the prompt/tool consistency, fail-fast matrix, privacy-safe logging, HTML rendering, and lazy-LLM determinism end-to-end.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3 (all TDD)
- **Commits:** 7 (3 RED → 3 GREEN TDD pairs + 1 chore)
- **Files modified:** 5 (including .gitignore)
- **Files created:** 1 SUMMARY (+ 1 new test file from scratch in Task 1 RED)
- **Tests added:** 39 (TestReactSystemPromptBuilder + TestReportEnginePreSeededObservations + TestReportSubparserPortfolioFlag + 9 module-level CLI tests + TestHtmlPortfolioSection + TestDeterministicEndToEnd)

## Task Commits

Each task followed a strict TDD RED → GREEN cycle:

1. **Task 1 RED: failing tests for prompt builder and pre-seeded observations** — `818cf05` (test)
2. **Task 1 GREEN: build_react_system_prompt + pre_seeded_observations in ReportEngine** — `72b82d6` (feat)
3. **Task 2 RED: failing CLI integration tests for --portfolio flag** — `c1cf8b6` (test)
4. **Task 2 GREEN: wire --portfolio CLI flag into _handle_report** — `3ed5782` (feat)
5. **Task 3 RED: failing HTML template and end-to-end determinism tests** — `f51b50e` (test)
6. **Task 3 GREEN: Portfolio Impact section cards in report.html.j2** — `c7c3d50` (feat)
7. **Chore: gitignore .alphaswarm/ runtime sentinel directory** — `ff273b9` (chore)

## Files Modified

### src/alphaswarm/report.py (+95 / -5)

**Prompt builder refactor:**
- Split `REACT_SYSTEM_PROMPT` into four module-private string templates: `_REACT_PROMPT_HEADER`, `_REACT_PROMPT_PORTFOLIO_LINE`, `_REACT_PROMPT_PORTFOLIO_MANDATE`, `_REACT_PROMPT_FOOTER`
- Added `build_react_system_prompt(*, include_portfolio: bool = False) -> str` that composes them conditionally
- `REACT_SYSTEM_PROMPT = build_react_system_prompt()` preserved as a module-level constant so existing `test_report.py` imports continue to work
- `_REACT_PROMPT_PORTFOLIO_MANDATE` includes two clauses: the `PORTFOLIO REPORTING CONTRACT` (MUST call + MUST summarize in FINAL ANSWER) and `CONTEXT AWARENESS (REPLAN-7)` (LLM is told the observation is already in its context and must NOT claim the data is missing)

**ReportEngine changes:**
- `__init__` gains two keyword-only kwargs: `system_prompt: str | None = None` (falls back to `REACT_SYSTEM_PROMPT`) and `pre_seeded_observations: list[ToolObservation] | None = None` (empty list default). The positional `ollama_client`/`model`/`tools` args are preserved for backwards compat.
- `run()` starts its local `observations` list from `list(self._pre_seeded)` instead of `[]`
- `run()` replaces the system prompt constant with `self._system_prompt`
- **(REPLAN-3/REPLAN-7 CORE CHANGE)** — After the initial `messages` list is built with the system + user messages and BEFORE the first `await self._client.chat(...)` call, a for-loop appends one `{"role": "user", "content": f"OBSERVATION: {obs.tool_name}: {json.dumps(obs.result, default=str)}"}` message for each pre-seeded observation. This puts the data physically in the model's context window on iteration 0.
- `run()` return path now de-dups: iterates tail observations (those added during the ReACT loop) and drops any whose `tool_name` already appears in `self._pre_seeded`, preserving pre-seeded-as-authoritative semantics
- `iteration = 0` initializer added before the loop so the post-loop log line works even when the loop body never executes (zero-iteration case)

### src/alphaswarm/cli.py (+143 / -2)

**Signature + imports:**
- `_handle_report` gains a `portfolio_path: str | None = None` parameter (fourth positional, default None)
- Local import block gains `parse_schwab_csv_async`, `build_portfolio_impact`, `PortfolioParseError`, `ToolObservation`, `build_react_system_prompt`

**Pre-call block (inserted between tools dict and ReportEngine construction):**
- `if portfolio_path is not None:` guard — entire block is a no-op when the flag is absent, preserving D-16 byte-identical behavior
- `Path(portfolio_path).exists()` check → prints `error: --portfolio file not found: <path>` to stderr and `raise SystemExit(2)`
- `Path.is_file()` check → prints `error: --portfolio path is not a regular file: <path>` and exits 2
- `parse_schwab_csv_async()` wrapped in try/except: `PortfolioParseError` → "CSV is malformed (<cls>)"; any other Exception → "failed to read --portfolio file (<cls>)"; both exit 2 and log via structlog with only `error_class=type(exc).__name__` (no exception message)
- Zero-equity check: `if equity_count == 0` → "CSV contained zero parseable equity holdings. Check that the 'Asset Type' column contains 'Equity' rows." and exit 2
- Successful branch: awaits `build_portfolio_impact(parse_result, gm, cycle_id)` once, wraps the result in a `ToolObservation(tool_name="portfolio_impact", tool_input={"cycle_id": cycle_id}, result=...)`, appends it to `pre_seeded_observations`, sets `include_portfolio = True`, and registers an `async def _portfolio_impact_tool(**kw) -> dict: return portfolio_impact_result` closure in the `tools` dict
- Three `logger.info` lines: `portfolio.parse_attempt` (path only), `portfolio.parse_success` (equity_count + excluded_count only), `portfolio.impact_built` (matched_count + gap_count + coverage_pct only)

**ReportEngine construction:**
- Passes `system_prompt=build_react_system_prompt(include_portfolio=include_portfolio)` so the dynamic prompt flows through
- Passes `pre_seeded_observations=pre_seeded_observations or None` — the `or None` normalization keeps the backwards-compat default path when no portfolio is provided

**Argparse + dispatcher:**
- `report` subparser gains `--portfolio` argument with UI-SPEC-compliant help text (contains "Schwab Individual-Positions CSV" and "loaded in-memory only")
- `main()` dispatcher branch for `report` passes `portfolio_path=args.portfolio` through to `_handle_report`

### src/alphaswarm/templates/report/report.html.j2 (+76 lines)

**Insertion point:** Immediately after the Market Context `{% endif %}` block and before the `{# Ticker mini-charts — up to 3 tickers #}` comment.

**Portfolio Impact - Matched Positions block:**
- `{% if sections.get("portfolio_impact") and sections["portfolio_impact"].matched_tickers %}` guard
- Coverage summary `<p>` with inline muted color: "Coverage: X/Y equity holdings matched to swarm consensus (Z.Z%)"
- Table with columns: Ticker, Shares (4dp), Market Value (display string), Swarm Signal (class="signal-{lower}"), Agreement ({(confidence*100)|round|int}%), Entity, Avg Sentiment (2dp)
- `{% elif sections.get("portfolio_impact") %}` branch renders the empty-state copy: "No held tickers match entities the swarm analyzed this cycle."
- Outer `{% endif %}` closes the whole block so rows only appear when portfolio_impact observation exists

**Portfolio Impact - Coverage Gaps block:**
- `{% if sections.get("portfolio_impact") and sections["portfolio_impact"].gap_tickers %}` guard
- Caption paragraph: "The following holdings had no corresponding entity in this simulation run:"
- Table columns: Ticker, Shares, Market Value (uses `g.market_value_display` from PortfolioGap, never ExcludedHolding directly per REPLAN-2), Reason
- Reason cell uses a `{% if g.reason == "non_equity" %}Non-equity ({{ g.asset_type }}){% else %}No simulation coverage{% endif %}` inline conditional
- `{% elif %}` branch renders "All equity holdings have swarm coverage in this simulation."

**Design constraints honored:**
- No new CSS classes (grep verified: `.portfolio-`, `.matched-`, `.gap-` all zero)
- No new `<style>` block (still single `<style>` tag in template)
- Reuses existing `.section`, `.signal-buy`, `.signal-sell`, `.signal-hold`, `table`, `thead`, `tbody` tokens
- Jinja autoescape is inherited from the assembler's HTML environment (autoescape=True) — verified by test_html_escapes_entity_name_with_html_chars

### tests/test_portfolio_integration.py (new file, 916 lines, 39 tests)

Organized into six test surfaces:

| Class / Group                                   | Tests | Scope                                                                                                                                  |
| ------------------------------------------------ | ----- | -------------------------------------------------------------------------------------------------------------------------------------- |
| TestReactSystemPromptBuilder                     |   8   | Default excludes portfolio; include_portfolio=True adds tool line + mandate + CONTEXT AWARENESS; all 8 existing tools preserved.     |
| TestReportEnginePreSeededObservations            |   4   | Empty default; accepts pre_seeded; returns pre-seeded even when LLM exits on iteration 0; pre-seeded injected as OBSERVATION msg.    |
| TestReportSubparserPortfolioFlag                 |   2   | argparse accepts --portfolio; cli.py source contains UI-SPEC help text verbatim.                                                     |
| CLI integration (module-level async functions)   |   9   | Missing path, directory path, empty equities, malformed CSV all raise SystemExit(2); no-regression without flag; pre-seed + tool; idempotent closure; privacy-safe logging. |
| TestHtmlPortfolioSection                         |  15   | Matched & gaps headings; rows; signal-buy/sell classes; no_simulation_coverage vs non_equity gap labels; coverage summary; integer agreement %; empty-state copy branches; XSS escape; no new CSS; offline self-contained. |
| TestDeterministicEndToEnd                        |   2   | Lazy-LLM scenario renders Portfolio Impact in both markdown (assemble) and HTML (assemble_html).                                     |

### .gitignore (+1 line)

Added `.alphaswarm/` — the write_sentinel runtime output directory that is now cleaned up so future test runs don't leave untracked state.

## How --portfolio Flows End-to-End

```
user invocation
    alphaswarm report --portfolio holdings.csv --format html
        │
        ▼
argparse (report subparser)
    args.portfolio = "holdings.csv"
        │
        ▼
main() dispatcher
    asyncio.run(_handle_report(..., portfolio_path=args.portfolio))
        │
        ▼
_handle_report (cli.py)
    1. Resolve cycle_id, load orchestrator model (existing behavior)
    2. Build base tools dict (8 entries)
    3. portfolio_path is not None → fail-fast validation
       • Path.exists() check
       • Path.is_file() check
       • parse_schwab_csv_async() with PortfolioParseError + generic Exception handling
       • equity_count == 0 check
       (each failure → SystemExit(2) + single-line stderr + structlog error with error_class only)
    4. build_portfolio_impact(parse_result, gm, cycle_id) — ONE deterministic await
    5. Wrap result in ToolObservation(tool_name="portfolio_impact", ...)
    6. pre_seeded_observations.append(obs)
    7. Register async portfolio_impact closure in tools dict (runtime, conditional)
    8. include_portfolio = True
        │
        ▼
ReportEngine construction
    system_prompt = build_react_system_prompt(include_portfolio=True)
        → adds portfolio_impact tool line + PORTFOLIO REPORTING CONTRACT + CONTEXT AWARENESS
    pre_seeded_observations = [portfolio_observation]
        │
        ▼
ReportEngine.run(cycle_id)
    1. observations = list(self._pre_seeded)  ← authoritative starting state
    2. messages = [{role:system, content:self._system_prompt}, {role:user, "Generate..."}]
    3. for obs in self._pre_seeded:
           messages.append({role:user, content:"OBSERVATION: portfolio_impact: <json>"})
        ← pre-computed data physically enters the model's context window
    4. Loop up to MAX_ITERATIONS calling ollama.chat() with messages
    5. Deterministic de-dup at return: pre-seeded entries win if LLM re-calls
        │
        ▼
ReportAssembler.assemble_html(observations, cycle_id)
    sections = {obs.tool_name: obs.result for obs in observations}
        → sections["portfolio_impact"] = PortfolioImpact dict
        │
        ▼
report.html.j2 rendering
    {% if sections.get("portfolio_impact") and ... %}
        → Portfolio Impact - Matched Positions card (if matched_tickers non-empty)
        → Portfolio Impact - Coverage Gaps card (if gap_tickers non-empty)
        │
        ▼
write_report(output_path, content) + write_sentinel(cycle_id, path)
    → reports/<cycle>_report.html on disk
```

**Key invariant:** Even if the ReACT LLM returns `FINAL_ANSWER` on iteration 0 without calling `portfolio_impact`, the pre-seeded observation is in both `observations` (via the `list(self._pre_seeded)` init) AND the `messages` context (via the injection loop). `TestDeterministicEndToEnd::test_lazy_llm_still_produces_portfolio_*_section` locks this guarantee.

## System Prompt Composition

`build_react_system_prompt(include_portfolio=False)`:

```
You are a post-simulation market analysis agent. Your task is to query the simulation graph and produce a comprehensive structured analysis report.

Available tools:
- consensus_summary: ...
- round_timeline: ...
...
- social_post_reach: ...
- FINAL_ANSWER: Signal that you have gathered enough data and are done

For each step, output exactly this format: ...
```

`build_react_system_prompt(include_portfolio=True)` adds two segments:

1. Between `social_post_reach` and `FINAL_ANSWER`:
   `- portfolio_impact: Map user's Schwab portfolio holdings against swarm entity consensus and list coverage gaps`

2. Appended after the `ACTION: FINAL_ANSWER` example:
   ```
   IMPORTANT — PORTFOLIO REPORTING CONTRACT:
   When portfolio_impact is in your available tools, you MUST call it at least
   once and you MUST include a paragraph in your FINAL ANSWER summarizing how
   swarm consensus aligns (or conflicts) with the user's positions. This is a
   hard requirement for the report.

   CONTEXT AWARENESS (REPLAN-7):
   You already have a portfolio_impact observation in your conversation context
   (it was injected before the first iteration as a user message starting with
   'OBSERVATION: portfolio_impact:'). You MUST reference it in your FINAL ANSWER
   with a narrative paragraph describing how swarm consensus aligns (or conflicts)
   with the user's positions. Do NOT claim the data is missing — it is already
   available in your context window.
   ```

The second clause is load-bearing: without the CONTEXT AWARENESS language, the model could see the OBSERVATION message and still claim the data is missing or try to fetch it.

## D-16 Regression Guard (no --portfolio = unchanged behavior)

`test_handle_report_without_portfolio_flag_is_unchanged` asserts the following on the captured `ReportEngine.__init__` kwargs when `portfolio_path=None` is passed:

- `"portfolio_impact" not in captured["tools"]` — tools dict has exactly the 8 pre-Phase-25 entries
- `"portfolio_impact" not in captured["system_prompt"]` — system prompt is the vanilla REACT_SYSTEM_PROMPT
- `"PORTFOLIO REPORTING CONTRACT" not in captured["system_prompt"]` — mandate clause absent
- `captured["pre_seeded_observations"] is None` — engine falls back to its empty-list default

This is the D-16 contract: `alphaswarm report` output must be byte-identical to pre-Phase-25 when the flag is absent.

## Fail-Fast Matrix

| Failure mode                          | Test                                                             | stderr snippet                                   | Exit |
| ------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------ | ---- |
| Path does not exist                   | test_handle_report_missing_portfolio_path_raises_system_exit    | "--portfolio file not found"                     | 2    |
| Path exists but is a directory        | test_handle_report_portfolio_path_is_directory_raises           | "not a regular file"                             | 2    |
| CSV parses but zero equity holdings   | test_handle_report_empty_equity_holdings_raises                  | "zero parseable equity holdings"                 | 2    |
| Malformed CSV (missing header row)    | test_handle_report_malformed_csv_raises                          | "malformed" OR "failed to read"                  | 2    |

All four paths log via structlog with only `error_class=type(exc).__name__` — no user data in logs.

## Privacy Audit

`test_logging_never_contains_holdings_data` loads a CSV with `AAPL` + `NVDA` holdings through the full `_handle_report` path (with a stub `fake_run` that short-circuits the LLM call), captures all log output at DEBUG level, and asserts:

- `"AAPL"`, `"NVDA"`, `"APPLE"`, `"NVIDIA"` never appear in log text
- `"$2,600"`, `"$2,500"` never appear in log text

Only `portfolio.parse_attempt (path=...)`, `portfolio.parse_success (equity_count=2, excluded_count=0)`, and `portfolio.impact_built (matched_count=1, gap_count=1, coverage_pct=50.0)` reach the log.

## Reviews Addressed (from 25-02-PLAN.md frontmatter)

| reviews_addressed entry                                                                                         | Locked by test(s)                                                                       |
| --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| ReACT tool non-determinism (HIGH, consensus): deterministic pre-call                                            | test_handle_report_with_portfolio_pre_seeds_observation_and_registers_tool; TestDeterministicEndToEnd::both |
| Mandatory narrative language (HIGH, Gemini): build_react_system_prompt(include_portfolio=True) MUST clause      | test_include_portfolio_true_contains_mandatory_clause                                   |
| Fail-fast on explicit --portfolio error (HIGH, Codex)                                                           | 4 SystemExit tests (missing, directory, empty equities, malformed)                       |
| Tool observation shape consistency (MEDIUM, Codex): PortfolioImpact TypedDict                                   | test_handle_report_with_portfolio_pre_seeds_observation_and_registers_tool               |
| Prompt/tool consistency tests in both directions (MEDIUM, Codex)                                                | test_handle_report_without_portfolio_flag_is_unchanged + _with_portfolio_ counterpart   |
| Privacy-safe logging (MEDIUM, Codex)                                                                            | test_logging_never_contains_holdings_data                                                |
| ReportEngine.__init__ compatibility audit (MEDIUM, Codex): new kwargs keyword-only with None default           | All existing test_report.py tests pass unchanged (48 tests green)                        |
| Jinja HTML escaping (LOW, Codex)                                                                                | test_html_escapes_entity_name_with_html_chars                                            |
| (REPLAN-2) HTML template consumes PortfolioGap only, never ExcludedHolding                                      | grep verification: excluded_holdings count == 0 in report.html.j2 and 10_portfolio_impact.j2 |
| (REPLAN-3) Pre-seeded observation injected into LLM conversation messages                                       | test_pre_seeded_observations_appear_in_llm_messages                                      |
| (REPLAN-7) Pre-seeded observation injection mechanism + system prompt context-awareness clause                  | test_pre_seeded_observations_appear_in_llm_messages + test_include_portfolio_true_contains_context_awareness_clause |
| (REPLAN-6) Static template registration vs runtime tool registration distinction                                | test_handle_report_without_portfolio_flag_is_unchanged (portfolio_impact not in runtime tools) + Plan 01 static registration still present |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Plan's monkeypatch strategy couldn't patch locally-imported symbols**
- **Found during:** Task 2 RED (writing CLI integration tests)
- **Issue:** The plan's literal test code used `monkeypatch.setattr(cli_module, "create_app_state", lambda ...)` but `create_app_state` is imported INSIDE `_handle_report` (not at module level), so `cli_module.create_app_state` doesn't exist as an attribute — `monkeypatch.setattr` would raise AttributeError.
- **Fix:** Introduced a `_patch_app_factory(monkeypatch, fake_app)` helper that patches `alphaswarm.app.create_app_state` (where the symbol IS defined at module level) and uses `monkeypatch.setattr(cli_module, "load_bracket_configs", ...)` / `generate_personas` for the config helpers that ARE module-level imports in cli.py. This preserves the plan's intent (stub out the real AppState factory and config chain) while respecting the actual import structure.
- **Files modified:** tests/test_portfolio_integration.py
- **Verification:** All 9 new CLI integration tests pass — _handle_report is successfully stubbed in each test without touching real Ollama/Neo4j.
- **Committed in:** c1cf8b6 (Task 2 RED)

**2. [Rule 3 — Blocking] Worktree HEAD was unrelated to plan base**
- **Found during:** Pre-execution worktree branch base check
- **Issue:** This parallel executor worktree's HEAD (`dfdf49d`) was an unrelated "workout-tracker" commit with no connection to the AlphaSwarm history. The expected base `c954ac0` (Plan 01 completion) was not an ancestor.
- **Fix:** `git reset --hard c954ac0731630a7c8869c7511be55bdaa947dc47` to align the worktree with Plan 01's final state before starting Plan 02 work.
- **Files modified:** None (git state only)
- **Verification:** `git log --oneline -5` confirms c954ac0 at HEAD, all Plan 01 artifacts present (portfolio.py, 10_portfolio_impact.j2, test_portfolio.py).
- **Committed in:** N/A (pre-plan setup)

**3. [Rule 3 — Blocking] `.alphaswarm/` sentinel directory created by privacy-logging test**
- **Found during:** Post-Task-3 git status check
- **Issue:** `test_logging_never_contains_holdings_data` drives `_handle_report` end-to-end without a `sentinel_dir` override, so `write_sentinel()` writes `.alphaswarm/last_report.json` to the working directory — an untracked runtime output file. Pre-existing behavior (Phase 15 sentinel contract) that had never been gitignored.
- **Fix:** Appended `.alphaswarm/` to `.gitignore` alongside the existing `results/` entry.
- **Files modified:** .gitignore
- **Verification:** `git status --short` shows clean tree after commit.
- **Committed in:** ff273b9 (chore commit)

**4. [Rule 2 — Missing critical functionality] `iteration` initializer for zero-loop case**
- **Found during:** Task 1 GREEN while editing ReportEngine.run()
- **Issue:** The post-loop log line `total_iterations=min(iteration + 1, MAX_ITERATIONS)` references the loop variable, which would raise `NameError` if the for-loop body never executes (pre-existing latent bug). With pre-seeded observations, a test that stubs `self._pre_seeded` and sets `ollama_client.chat` to return FINAL_ANSWER on first iteration still enters the loop, so this isn't triggered in practice — but the injection loop I added above the main loop made me notice it. Added a defensive `iteration = 0` before the `for iteration in range(...)` line.
- **Fix:** One-line initializer.
- **Files modified:** src/alphaswarm/report.py
- **Verification:** All 48 test_report.py tests still pass + all 39 new integration tests pass.
- **Committed in:** 72b82d6 (Task 1 GREEN — rolled into the same commit)

---

**Total deviations:** 4 auto-fixed (2 test/infra blocking, 1 worktree setup, 1 defensive correctness hardening). None required changing the plan's contract or scope.

## Issues Encountered

None beyond the deviations above. No RuntimeWarnings, no flaky tests, no integration failures in the portfolio scope.

## User Setup Required

None — this plan is purely CLI + template wiring on top of Plan 01's library code. No new dependencies, no service configuration.

## Test Counts

| Suite                              | Tests | Status |
| ---------------------------------- | ----- | ------ |
| tests/test_portfolio_integration.py |  39   | PASS   |
| tests/test_portfolio.py            |  73   | PASS   |
| tests/test_report.py               |  48   | PASS   |
| tests/test_cli.py                  |  19   | PASS   |
| **Combined (scoped)**              | **179** | **PASS** |
| Full repo suite (minus graph/inference integration) | 677 | PASS |

## Requirements Completed

- **PORTFOLIO-01** (CSV parsing + ticker-entity bridge): completed across Plan 01 + 02. Plan 02 wires the CLI entry point.
- **PORTFOLIO-02** (markdown Portfolio Impact section): completed via Plan 01 template + Plan 02 end-to-end pipeline.
- **PORTFOLIO-03** (HTML Portfolio Impact section): completed via Plan 02 report.html.j2 cards.
- **PORTFOLIO-04** (narrative mandate): completed via PORTFOLIO REPORTING CONTRACT clause + CONTEXT AWARENESS clause + deterministic pre-call guarantee. Even if the LLM is lazy, the data is in both the returned observations AND the conversation context window.

## Self-Check: PASSED

Verified:

- [x] src/alphaswarm/report.py modified (build_react_system_prompt, ReportEngine kwargs, run() injection, de-dup)
- [x] src/alphaswarm/cli.py modified (--portfolio flag, fail-fast, pre-call block, dispatcher wiring)
- [x] src/alphaswarm/templates/report/report.html.j2 modified (two Portfolio Impact section cards)
- [x] tests/test_portfolio_integration.py created (39 tests, 6 classes)
- [x] .planning/phases/25-portfolio-impact-analysis/25-02-SUMMARY.md exists (this file)
- [x] .gitignore includes `.alphaswarm/` (runtime sentinel directory)
- [x] Commit 818cf05 exists (Task 1 RED)
- [x] Commit 72b82d6 exists (Task 1 GREEN)
- [x] Commit c1cf8b6 exists (Task 2 RED)
- [x] Commit 3ed5782 exists (Task 2 GREEN)
- [x] Commit f51b50e exists (Task 3 RED)
- [x] Commit c7c3d50 exists (Task 3 GREEN)
- [x] Commit ff273b9 exists (chore)
- [x] `uv run pytest tests/test_portfolio_integration.py tests/test_portfolio.py tests/test_report.py tests/test_cli.py -q` → 179 passed
- [x] `uv run python -m alphaswarm report --help` includes `--portfolio`
- [x] `uv run python -c "from alphaswarm.report import REACT_SYSTEM_PROMPT; assert 'portfolio_impact' not in REACT_SYSTEM_PROMPT"` exits 0
- [x] `uv run python -c "from alphaswarm.report import build_react_system_prompt; p = build_react_system_prompt(include_portfolio=True); assert 'MUST include a paragraph' in p; assert 'CONTEXT AWARENESS' in p"` exits 0
- [x] `grep -c '\.portfolio-\|\.matched-\|\.gap-' src/alphaswarm/templates/report/report.html.j2` returns 0 (no new CSS classes)
- [x] `grep -c "excluded_holdings" src/alphaswarm/templates/report/report.html.j2` returns 0 (REPLAN-2)
- [x] `grep -c "excluded_holdings" src/alphaswarm/templates/report/10_portfolio_impact.j2` returns 0 (REPLAN-2)
- [x] `grep -c "<style>" src/alphaswarm/templates/report/report.html.j2` returns 1 (no duplicate style block)
- [x] No stubs in new/modified code — the `_portfolio_impact_tool` closure returns real pre-computed data, not a placeholder
- [x] Working tree clean after all commits

---
*Phase: 25-portfolio-impact-analysis*
*Plan: 02*
*Completed: 2026-04-10*
