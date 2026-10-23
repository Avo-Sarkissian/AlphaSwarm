"""Output caps for every LLM call site (docs/DECISIONS.md#adr-output-caps).

Callers pass these as ``max_tokens``: the Ollama adapter sends the value as
``options["num_predict"]``, the cloud adapters as their ``max_tokens``.
tests/invariants/test_output_caps.py fails for any chat/chat_structured call
without a cap. The report narrative (alphaswarm.report.NARRATIVE_MAX_TOKENS,
1200) and the advisory (alphaswarm.advisory.engine.ADVISORY_MAX_TOKENS, 3000)
keep their caps next to their prompts.
"""

from __future__ import annotations

from typing import Final

# Modelfile fallbacks (PARAMETER num_predict) for a caller that passes no cap;
# pinned to modelfiles/ by tests/invariants/test_modelfile_mirrors.py.
WORKER_MODELFILE_NUM_PREDICT: Final = 400
ORCHESTRATOR_MODELFILE_NUM_PREDICT: Final = 4096

# Worker role. A decision is about 100-150 tokens; 400 stops repetition loops.
WORKER_DECISION_MAX_TOKENS: Final = WORKER_MODELFILE_NUM_PREDICT
DECISION_NARRATIVE_MAX_TOKENS: Final = 400  # one paragraph, written on first interview
INTERVIEW_REPLY_MAX_TOKENS: Final = 600
INTERVIEW_SUMMARY_MAX_TOKENS: Final = 300

# Orchestrator role (reasoning off, docs/DECISIONS.md#adr-think-off).
SEED_MAX_TOKENS: Final = 1024  # entities and sentiment as JSON
MODIFIERS_MAX_TOKENS: Final = 1024  # one short focus line per bracket

# Anthropic requires max_tokens on every request; adapter defaults per role.
ANTHROPIC_ORCHESTRATOR_DEFAULT_MAX_TOKENS: Final = 8192
ANTHROPIC_WORKER_DEFAULT_MAX_TOKENS: Final = 512
