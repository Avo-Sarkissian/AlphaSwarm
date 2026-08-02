# Deferred Items — Phase 41.6 / Quick Task 260512-jqn

Pre-existing test failures and known issues encountered during execution
that are OUT OF SCOPE for the touched plans. Each entry must be addressed
in a future plan.

## Pre-existing test failures (discovered 2026-05-12 during quick task 260512-jqn)

These failures exist on master before any 260512-jqn change and are not
caused by ITEM 2 (or any other ITEM in this task). They live in
`tests/test_simulation.py` around the `_format_peer_context` helper:

- `test_format_peer_context_structure` — asserts `"[quants]" in result`
  but the actual format is `"[agent_00|quants]"`. The format string in
  `simulation.py:_format_peer_context` includes both agent_id and bracket
  joined with `|`; the test was written against an earlier shape.
- `test_format_peer_context_single_post_exceeds_budget` — same root cause.
- `test_format_peer_context_prompt_guard_preserved` — same root cause.
- `test_format_peer_context_line_format` — same root cause.

Fix is mechanical (update the assertions to match the current `[agent|bracket]`
format) but belongs to a peer-context plan, not the post-run follow-ups.
