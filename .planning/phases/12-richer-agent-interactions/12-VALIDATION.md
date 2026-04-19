---
phase: 12
slug: richer-agent-interactions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] asyncio_mode = "auto" |
| **Quick run command** | `uv run pytest tests/test_graph.py tests/test_simulation.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x --tb=short` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_graph.py tests/test_simulation.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-W0-stubs | TBD | 0 | SOCIAL-01, SOCIAL-02 | stub | `uv run pytest tests/ -x -q` | ❌ W0 | ⬜ pending |
| 12-schema-post | TBD | 1 | SOCIAL-01 | unit | `uv run pytest tests/test_graph.py -x -k "schema_statements_includes_post_index"` | ❌ W0 | ⬜ pending |
| 12-write-posts | TBD | 1 | SOCIAL-01 | unit | `uv run pytest tests/test_graph.py -x -k "write_posts"` | ❌ W0 | ⬜ pending |
| 12-write-posts-skip | TBD | 1 | SOCIAL-01 | unit | `uv run pytest tests/test_graph.py -x -k "write_posts_skip_parse_error"` | ❌ W0 | ⬜ pending |
| 12-read-ranked-posts | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_graph.py -x -k "read_ranked_posts"` | ❌ W0 | ⬜ pending |
| 12-ranked-posts-fallback | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_graph.py -x -k "ranked_posts_fallback"` | ❌ W0 | ⬜ pending |
| 12-write-read-post-edges | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_graph.py -x -k "write_read_post_edges"` | ❌ W0 | ⬜ pending |
| 12-format-peer-budget | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_budget"` | ❌ W0 | ⬜ pending |
| 12-format-peer-word | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_word_boundary"` | ❌ W0 | ⬜ pending |
| 12-format-peer-guard | TBD | 1 | SOCIAL-02 | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_prompt_guard"` | ✅ update | ⬜ pending |
| 12-sim-integration | TBD | 2 | SOCIAL-01, SOCIAL-02 | unit (mocked) | `uv run pytest tests/test_simulation.py -x -k "run_simulation_writes_posts"` | ❌ W0 | ⬜ pending |
| 12-graph-integration | TBD | 2 | SOCIAL-01, SOCIAL-02 | integration | `uv run pytest tests/test_graph_integration.py -x -k "posts_and_read_post"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_graph.py` — stubs for write_posts, read_ranked_posts, write_read_post_edges (SOCIAL-01, SOCIAL-02)
- [ ] `tests/test_simulation.py` — stubs for updated _format_peer_context with budget enforcement; update existing _format_peer_context tests for new signature
- [ ] `tests/test_simulation.py` — stub for run_simulation post/READ_POST integration (mocked graph_manager)
- [ ] `tests/test_graph_integration.py` — stubs for Post + READ_POST integration tests (real Neo4j)
- [ ] `tests/conftest.py` — add Post node cleanup to graph_manager fixture teardown

*Existing pytest + pytest-asyncio infrastructure is sufficient — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Agent outputs in Rounds 2-3 show observable reactions to peer rationale (citations, agreement, disagreement) vs Round 1 baseline | SOCIAL-02 (success criterion 4) | Requires running full simulation with live Ollama models; output quality is subjective | Run `uv run alphaswarm simulate` with a seed rumor, compare Round 1 vs Round 2/3 rationale text for reaction language |

---

## Existing Tests That Must Not Break

- `test_format_peer_context_structure` — signature changes (PeerDecision → RankedPost), test must be updated
- `test_format_peer_context_truncates_rationale` — truncation logic changes (80-char → 4000-char budget), test must be updated
- `test_format_peer_context_empty_peers` — behavior unchanged, should pass
- `test_dispatch_round_*` — if `_dispatch_round()` refactored, these may need updates
- `test_run_simulation_*` — mock graph_manager needs new method mocks (write_posts, read_ranked_posts, write_read_post_edges)

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
