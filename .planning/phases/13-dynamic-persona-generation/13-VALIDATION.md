---
phase: 13
slug: dynamic-persona-generation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `uv run pytest tests/test_config.py tests/test_personas.py tests/test_parsing.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_config.py tests/test_personas.py tests/test_parsing.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | PERSONA-01 | unit | `uv run pytest tests/test_config.py::test_sanitize_entity_name_truncation tests/test_config.py::test_sanitize_entity_name_strips_control_chars tests/test_config.py::test_sanitize_entity_name_preserves_punctuation -x` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | PERSONA-01 | unit | `uv run pytest tests/test_seed.py::test_parsed_modifiers_result_construction -x` | ❌ W0 | ⬜ pending |
| 13-01-03 | 01 | 1 | PERSONA-01 | unit | `uv run pytest tests/test_parsing.py::test_parse_modifiers_tier1 tests/test_parsing.py::test_parse_modifiers_tier2 tests/test_parsing.py::test_parse_modifiers_tier3_fallback tests/test_parsing.py::test_parse_modifiers_partial_fallback tests/test_parsing.py::test_parse_modifiers_case_insensitive -x` | ❌ W0 | ⬜ pending |
| 13-02-01 | 02 | 2 | PERSONA-02 | unit | `uv run pytest tests/test_personas.py::test_generate_personas_with_modifiers_count tests/test_personas.py::test_generate_personas_with_modifiers_content tests/test_personas.py::test_generate_personas_backward_compatible -x` | ❌ W0 | ⬜ pending |
| 13-02-02 | 02 | 2 | PERSONA-02 | unit | `uv run pytest tests/test_config.py::test_modifier_length_cap -x` | ❌ W0 | ⬜ pending |
| 13-02-03 | 02 | 2 | PERSONA-01, PERSONA-02 | regression | `uv run pytest tests/test_personas.py -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_config.py` — add `test_sanitize_entity_name_truncation`, `test_sanitize_entity_name_strips_control_chars`, `test_sanitize_entity_name_preserves_punctuation`, `test_modifier_length_cap` (4 tests)
- [ ] `tests/test_seed.py` — add `test_parsed_modifiers_result_construction` (construction, frozen verification)
- [ ] `tests/test_parsing.py` — add `test_parse_modifiers_tier1`, `test_parse_modifiers_tier2`, `test_parse_modifiers_tier3_fallback`, `test_parse_modifiers_partial_fallback`, `test_parse_modifiers_case_insensitive` (5 tests)
- [ ] `tests/test_personas.py` — add `test_generate_personas_with_modifiers_count`, `test_generate_personas_with_modifiers_content`, `test_generate_personas_backward_compatible` (3 tests)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Modifier generation produces contextually relevant strings (e.g., "quantitative analyst modeling EV supply chain dynamics" for a Tesla seed rumor) | PERSONA-01 | LLM output quality — cannot be deterministically asserted | Run `uv run python -m alphaswarm run --seed "Tesla reports battery supply chain disruption"`, inspect agent system prompts in logs for modifier strings that reference Tesla/EV domain |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
