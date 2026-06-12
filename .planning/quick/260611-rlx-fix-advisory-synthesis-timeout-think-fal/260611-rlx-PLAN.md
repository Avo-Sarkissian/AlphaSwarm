---
phase: quick-260611-rlx
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/alphaswarm/advisory/engine.py
  - src/alphaswarm/web/routes/advisory.py
  - frontend/src/components/ReportModal.tsx
  - tests/unit/test_advisory.py
  - tests/unit/test_advisory_route.py
autonomous: true
requirements: [QUICK-260611-rlx]

must_haves:
  truths:
    - "Advisory synthesis completes without timing out (think=False suppresses qwen3.6 reasoning tokens on the 11.3 t/s orchestrator)"
    - "When the advisory background task succeeds, report generation auto-fires for the same cycle"
    - "Advisory failure or cancellation does NOT trigger report generation"
    - "The auto-fired report task survives until it runs (strong reference held; not GC'd as a weak-ref task)"
    - "The report route's 409 orchestrator-serialization guard remains authoritative and is tolerated by the chain"
    - "Report generation never re-triggers advisory (no loop)"
    - "ReportModal copy reflects that reports auto-generate after the advisory, with manual Generate as a fallback/regenerate path"
  artifacts:
    - path: "src/alphaswarm/advisory/engine.py"
      provides: "_infer_with_retry with think=False on both chat calls"
      contains: "think=False"
    - path: "src/alphaswarm/web/routes/advisory.py"
      provides: "_auto_trigger_report coroutine + chain scheduling from _on_advisory_task_done success branch with strong task reference"
      contains: "_auto_trigger_report"
  key_links:
    - from: "src/alphaswarm/web/routes/advisory.py::_on_advisory_task_done"
      to: "src/alphaswarm/web/routes/advisory.py::_auto_trigger_report"
      via: "asyncio.create_task on the success branch, strong ref in module-level set"
      pattern: "asyncio\\.create_task\\(.*_auto_trigger_report"
    - from: "src/alphaswarm/web/routes/advisory.py::_auto_trigger_report"
      to: "POST /api/report/{cycle_id}/generate"
      via: "httpx.ASGITransport in-process POST"
      pattern: "report/.*generate"
---

<objective>
Fix the advisory synthesis HTTP 500 timeout and chain report auto-generation after a successful advisory.

Purpose:
- Bug 1: `_infer_with_retry` in advisory/engine.py omits `think=False`, so qwen3.6:27b-nvfp4 (11.3 t/s decode) emits reasoning tokens that push the single advisory chat past the 600s client timeout. The done-callback records that timeout into `app.state.advisory_generation_error[cycle_id]`, making GET /api/advisory/{cycle_id} return 500 permanently.
- Feature 2: Reports are currently manual-only. After a successful advisory, the same orchestrator is warm and the cycle is COMPLETE — auto-fire report generation so the user gets both artifacts without a second manual step.

Output: think=False on both advisory engine chat calls; an in-process report auto-trigger chained off the advisory success branch; updated ReportModal copy; tests covering both.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md

<interfaces>
<!-- Extracted from codebase — executor should use these directly, no exploration needed. -->

From src/alphaswarm/advisory/engine.py (_infer_with_retry, ~line 281):
  Two await calls to `ollama_client.chat(model=..., messages=..., format="json")`:
    - line ~291: initial call
    - line ~312: validation-retry call (retry_response)
  Both currently OMIT `think`. Every other call path passes think=False
  (seed.py:73, report.py:160, interview.py:140/174, worker.py).

From src/alphaswarm/web/simulation_manager.py (the pattern to mirror):
  async def _auto_trigger_advisory(app: FastAPI, cycle_id: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(f"/api/advisory/{cycle_id}")
    # 202 -> info "accepted"; 409 -> info "skipped_conflict";
    # 503 -> warning "skipped_unavailable"; else -> warning "unexpected_status";
    # except Exception -> log.exception, swallow.

From src/alphaswarm/web/routes/advisory.py (_on_advisory_task_done, line 212):
  SYNC done-callback(task, cycle_id, app). Branches:
    - task.cancelled() -> record error, return  (DO NOT chain)
    - exc = task.exception(); exc is not None -> record error, return  (DO NOT chain)
    - exc is None -> log.info "advisory_task_completed", return  (SUCCESS — chain here)
  MUST NOT raise (FastAPI loop swallows). Callback only has cycle_id + app
  (no `self`), so the strong-ref set must be MODULE-LEVEL or on app.state.

From src/alphaswarm/web/routes/report.py:
  POST /report/{cycle_id}/generate returns 202 accepted; 409 if report_task
  in flight OR advisory_task in flight (bidirectional guard); 503 if services
  unavailable; 400 if cycle_id invalid. This route NEVER triggers advisory
  (verified — no advisory call anywhere in report.py), so the chain cannot loop.

From frontend/src/components/ReportModal.tsx (lines 181-187):
  The empty-state paragraph currently reads:
    "Reports are NOT auto-generated on cycle complete (unlike the advisory).
     Click below to kick off generation — ..."
  Keep the modal structure and the "Generate report" button; only revise copy.

From tests/unit/test_advisory.py (FakeOllamaClient, line 35):
  async def chat(self, model, messages, format=None, **_) tracks only
  self.calls.append(messages). It SWALLOWS think into **_. Must be extended
  to capture the think kwarg so the new test can assert think is False.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add think=False to both advisory engine chat calls + capture-kwarg test</name>
  <files>src/alphaswarm/advisory/engine.py, tests/unit/test_advisory.py</files>
  <behavior>
    - Test: a FakeOllamaClient that records the `think` kwarg per call shows
      think=False on BOTH the initial chat and the validation-retry chat.
    - Drive the retry path with a malformed-then-valid canned pair so both
      chat calls execute in one test (mirror existing test at test_advisory.py:339
      which already uses canned=[malformed, valid]).
  </behavior>
  <action>
    In src/alphaswarm/advisory/engine.py `_infer_with_retry` (~line 281): add `think=False` to BOTH `ollama_client.chat(...)` calls — the initial call (~line 291) and the validation-retry call `retry_response` (~line 312). Keep `format="json"` on both; place `think=False` alongside it. Rationale: qwen3.6 defaults thinking ON and the MLX orchestrator decodes at ~11.3 t/s, so reasoning tokens exceed the 600s client timeout (consistency with seed.py:73, report.py:160, interview.py:140/174, worker.py — all pass think=False).
    In tests/unit/test_advisory.py: extend the existing `FakeOllamaClient.chat` (line 42) so it captures the `think` kwarg explicitly — add a `think` parameter (default None) ahead of `**_` and append to a new `self.think_calls: list` (initialized in `__init__` alongside `self.calls`). Do NOT remove `**_` (other kwargs like format still flow through). Add one test `test_infer_with_retry_passes_think_false` that constructs the FakeOllamaClient with `canned=[malformed_json, valid_json]` (reuse the malformed/valid fixtures already in the file's retry test ~line 339), invokes the advisory synthesis path that reaches `_infer_with_retry`, and asserts `fake_ollama.think_calls == [False, False]` (both calls captured think=False).
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/unit/test_advisory.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>Both chat calls in _infer_with_retry pass think=False; new test asserts think_calls == [False, False]; full test_advisory.py suite green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Chain report auto-trigger off advisory success + done-callback tests</name>
  <files>src/alphaswarm/web/routes/advisory.py, tests/unit/test_advisory_route.py</files>
  <behavior>
    - Success branch: when _on_advisory_task_done runs with a task that is NOT
      cancelled and has NO exception, it schedules _auto_trigger_report(app, cycle_id)
      via asyncio.create_task AND keeps a strong reference (module-level set).
    - Failure branch: task.exception() is not None -> NO report task scheduled.
    - Cancel branch: task.cancelled() -> NO report task scheduled.
    - _auto_trigger_report mirrors _auto_trigger_advisory: in-process POST to
      /api/report/{cycle_id}/generate, swallows 202/409/503/other + Exception.
  </behavior>
  <action>
    In src/alphaswarm/web/routes/advisory.py:
    1. Add a module-level `async def _auto_trigger_report(app: FastAPI, cycle_id: str) -> None` mirroring `_auto_trigger_advisory` in simulation_manager.py (httpx.ASGITransport, base_url "http://testserver", POST `/api/report/{cycle_id}/generate`). Swallow non-202 with logged scalar outcomes: 202 -> log.info "auto_report_trigger_accepted"; 409 -> log.info "auto_report_trigger_skipped_conflict" (the report route's bidirectional orchestrator-serialization 409 stays authoritative and is tolerated here); 503 -> log.warning "auto_report_trigger_skipped_unavailable"; else -> log.warning "auto_report_trigger_unexpected_status"; `except Exception -> log.exception("auto_report_trigger_failed", cycle_id=cycle_id)` and swallow. Log scalars only (cycle_id, status) — never portfolio objects.
    2. Add a module-level strong-ref set near the top of the module: `_report_chain_tasks: set[asyncio.Task[Any]] = set()` (the done-callback is sync and only receives cycle_id + app, so the ref set cannot live on `self`; the event loop holds only weak refs to bare tasks — mirror the `_bg_tasks` rationale in SimulationManager).
    3. In `_on_advisory_task_done` (line 212), on the SUCCESS branch only (the `exc is None` path at ~line 235, after the cancelled-return and the exception-record-return), schedule the chain: `chain = asyncio.create_task(_auto_trigger_report(app, cycle_id), name=f"auto_report_{cycle_id}")`, then `_report_chain_tasks.add(chain)` and `chain.add_done_callback(_report_chain_tasks.discard)`. Wrap the scheduling in try/except (the callback MUST NOT raise — match the defensive try/except already used in the failure/cancel branches). Do NOT schedule on the cancelled or exception branches (orchestrator may be wedged — don't pile on). Keep the existing `log.info("advisory_task_completed", ...)` line.
    Loop-safety note (no code beyond the above): report.py contains no advisory call, so report -> advisory recursion is impossible; the only chain is advisory-success -> report.
    In tests/unit/test_advisory_route.py: add tests using the existing `_make_app` + `_neutralize_background_task` fixtures.
      (a) `test_advisory_done_success_schedules_report`: build a fake completed task (`MagicMock(spec=asyncio.Task)` with `.cancelled()` -> False and `.exception()` -> None), monkeypatch `alphaswarm.web.routes.advisory._auto_trigger_report` with an AsyncMock, call `_on_advisory_task_done(task, "cycle_01", app)` inside a running loop, `await asyncio.sleep(0)` to let the created task start, and assert the AsyncMock was awaited once with (app, "cycle_01"). Drain `_report_chain_tasks` afterward.
      (b) `test_advisory_done_failure_no_report`: task with `.cancelled()` -> False and `.exception()` -> some Exception; assert the `_auto_trigger_report` AsyncMock was NOT called.
      (c) `test_advisory_done_cancelled_no_report`: task with `.cancelled()` -> True; assert NOT called.
    Import `_on_advisory_task_done`, `_auto_trigger_report`, and `_report_chain_tasks` from `alphaswarm.web.routes.advisory`.
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/unit/test_advisory_route.py tests/unit/test_auto_advisory_trigger.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>_auto_trigger_report exists and mirrors the advisory trigger (202/409/503/other + Exception swallowed, scalar logs); success branch schedules it with a strong ref; failure and cancel branches do not; all three new tests + existing route/trigger suites green.</done>
</task>

<task type="auto">
  <name>Task 3: Update ReportModal copy to reflect auto-generation</name>
  <files>frontend/src/components/ReportModal.tsx</files>
  <action>
    In frontend/src/components/ReportModal.tsx, revise the empty-state paragraph (lines 181-187) that currently reads "Reports are NOT auto-generated on cycle complete (unlike the advisory). Click below to kick off generation — ...". New copy: reports now auto-generate after the advisory completes; the manual "Generate report" button below remains as a fallback / regenerate path if auto-generation has not yet started or you want a fresh pass. Keep the ~5-10 min wall-clock-on-M1-Max note. Do NOT change the modal structure, the surrounding conditional render guards, or the `<button onClick={handleGenerate}>` Generate report button — copy text only. NOTE: the target file is ReportModal.tsx (the planning brief said v2.tsx, but the string lives in ReportModal.tsx — verified via grep).
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && grep -q "auto-generate" src/components/ReportModal.tsx && ! grep -q "Reports are NOT auto-generated" src/components/ReportModal.tsx && npm run build 2>&1 | tail -8</automated>
  </verify>
  <done>Old "Reports are NOT auto-generated" copy removed; new auto-generation copy present; Generate button + modal structure unchanged; frontend build green.</done>
</task>

</tasks>

<verification>
Full backend suite for touched modules + frontend build:

```bash
cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" && uv run pytest tests/unit/test_advisory.py tests/unit/test_advisory_route.py tests/unit/test_auto_advisory_trigger.py -q
cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npm run build
```

Backend restart required to pick up Python changes (uvicorn does not hot-reload); browser hard-refresh for the frontend.
</verification>

<success_criteria>
- Both `ollama_client.chat(...)` calls in `_infer_with_retry` pass `think=False` (verified by `think_calls == [False, False]`).
- `_auto_trigger_report` exists in advisory.py, mirrors `_auto_trigger_advisory` (in-process POST, swallows 202/409/503/other + Exception, scalar-only logs).
- `_on_advisory_task_done` schedules the report chain ONLY on the success branch, with a module-level strong reference; failure and cancel branches do not.
- The report route's existing 409 guard is untouched and tolerated by the chain (logged as skipped_conflict).
- Report generation cannot re-trigger advisory (report.py has no advisory call — no loop).
- ReportModal copy updated; Generate button retained as fallback/regenerate.
- All touched test suites green; frontend build green.
</success_criteria>

<output>
Create `.planning/quick/260611-rlx-fix-advisory-synthesis-timeout-think-fal/260611-rlx-SUMMARY.md` when done.
</output>
