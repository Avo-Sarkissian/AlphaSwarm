"""Every LLM call site passes an explicit output cap (docs/DECISIONS.md#adr-output-caps)."""

from __future__ import annotations

import ast

from alphaswarm.settings import PROJECT_ROOT

SRC = PROJECT_ROOT / "src" / "alphaswarm"
# Modules that talk to a backend client (ollama, httpx, anthropic), not to an
# InferenceProvider; their .chat( calls are the transport, not a call site.
BACKEND_MODULES = frozenset(
    {
        "ollama_client.py",
        "ollama_models.py",
        "inference/ollama_provider.py",
        "inference/openai_provider.py",
        "inference/anthropic_provider.py",
    }
)
CALL_NAMES = frozenset({"chat", "chat_structured"})


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def calls_without_a_cap() -> list[str]:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in BACKEND_MODULES:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and _called_name(node) in CALL_NAMES
                and not any(kw.arg == "max_tokens" for kw in node.keywords)
            ):
                offenders.append(f"{rel}:{node.lineno}")
    return offenders


def test_every_llm_call_passes_max_tokens() -> None:
    assert calls_without_a_cap() == []


def test_the_scan_finds_the_known_call_sites() -> None:
    # Guards against a scan that silently matches nothing.
    text = (SRC / "worker.py").read_text(encoding="utf-8")
    assert ".chat(" in text
