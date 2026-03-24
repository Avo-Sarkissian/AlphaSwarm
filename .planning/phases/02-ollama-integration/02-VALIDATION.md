---
phase: 2
slug: ollama-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~15 seconds (unit) / ~60 seconds (with integration) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | INFRA-03/04/08 | unit | `uv run pytest tests/test_ollama_client.py -x` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 0 | INFRA-08 | unit | `uv run pytest tests/test_parsing.py -x` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 0 | INFRA-04 | unit | `uv run pytest tests/test_worker.py -x` | ❌ W0 | ⬜ pending |
| 2-01-04 | 01 | 0 | INFRA-03 | unit | `uv run pytest tests/test_models.py -x` | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 1 | INFRA-04 | unit | `uv run pytest tests/test_ollama_client.py::test_no_num_ctx -x` | ❌ W0 | ⬜ pending |
| 2-02-02 | 02 | 1 | INFRA-04 | unit | `uv run pytest tests/test_ollama_client.py::test_backoff_retry -x` | ❌ W0 | ⬜ pending |
| 2-02-03 | 02 | 1 | INFRA-08 | unit | `uv run pytest tests/test_parsing.py::test_tier1_json_parse -x` | ❌ W0 | ⬜ pending |
| 2-02-04 | 02 | 1 | INFRA-08 | unit | `uv run pytest tests/test_parsing.py::test_tier2_regex_extract -x` | ❌ W0 | ⬜ pending |
| 2-02-05 | 02 | 1 | INFRA-08 | unit | `uv run pytest tests/test_parsing.py::test_tier3_parse_error -x` | ❌ W0 | ⬜ pending |
| 2-02-06 | 02 | 1 | INFRA-04/08 | unit | `uv run pytest tests/test_worker.py::test_semaphore_lifecycle -x` | ❌ W0 | ⬜ pending |
| 2-03-01 | 03 | 2 | INFRA-03 | integration | `uv run pytest tests/test_models.py::test_sequential_load -x` | ❌ W0 | ⬜ pending |
| 2-03-02 | 03 | 2 | ALL | integration | `uv run pytest tests/test_integration_inference.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ollama_client.py` — OllamaClient wrapper unit tests with mocked AsyncClient
- [ ] `tests/test_parsing.py` — 3-tier parse fallback tests with sample LLM outputs
- [ ] `tests/test_worker.py` — agent_worker context manager semaphore lifecycle tests
- [ ] `tests/test_models.py` — sequential model load/unload tests with mocked ollama ps()
- [ ] `tests/test_integration_inference.py` — end-to-end single agent inference stub (requires running Ollama or comprehensive mock)
- [ ] `src/alphaswarm/errors.py` — OllamaInferenceError exception class (referenced by all other test files)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| qwen3.5:32b model actually loads on M1 Max without OOM | INFRA-03 | Requires physical Ollama instance with model pulled | Run `ollama run qwen3.5:32b` and verify with `ollama ps` |
| qwen3.5:7b model tag is valid on Ollama library | INFRA-03 | Model tag validity cannot be checked without live Ollama | Run `ollama pull qwen3.5:7b` and check exit code |
| High Reasoning mode (think=True) produces `<think>` block stripped from final output | INFRA-04 | Requires live model with thinking support | Send a prompt with `think=True` and inspect raw response |
| Memory actually freed after keep_alive=0 unload | INFRA-03 | psutil/memory_pressure report varies on Apple Silicon | Check `ollama ps` shows empty after unload call |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
