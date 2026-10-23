"""Schema-constrained structured output with parse fallbacks and one validated retry.

``chat_structured`` is the single path from an orchestrator reply to a typed
object (docs/DECISIONS.md#adr-structured-output):

1. send ``response_schema`` = the output model's JSON schema made portable by
   ``inference.schema.to_portable_schema`` (or the caller's ``schema`` override);
2. tier 1: validate the reply as JSON; tier 2: validate JSON candidates found
   after stripping code fences or surrounding prose;
3. on failure, retry with the validation error locations and messages appended
   as a correction turn. Neither the rejected reply nor its input values are
   sent back: a reply can echo prompt data (on the advisory path, holdings),
   so the retry carries field errors only (docs/DECISIONS.md#adr-holdings-isolation);
4. after ``retries`` extra attempts, raise ``StructuredOutputError`` (tier 3).

Provider exceptions (AuthError, BudgetExceededError, InferenceError) are never
caught here. Worker decisions keep their own path (``worker.DECISION_JSON_SCHEMA``
plus ``parsing.parse_agent_decision``); interviews are free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Generic, Literal, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from alphaswarm.errors import StructuredOutputError
from alphaswarm.inference.schema import to_portable_schema
from alphaswarm.logging import validation_error_details, validation_error_location

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.inference.types import InferenceMessage

log = structlog.get_logger(component="inference.structured")

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE_RE: Final = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_GREEDY_OBJECT_RE: Final = re.compile(r"\{.*\}", re.DOTALL)
_MAX_ERRORS_SHOWN: Final = 8


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """A validated reply: the value, the parse tier (1 direct, 2 extracted), attempts, raw text."""

    value: T
    parse_tier: Literal[1, 2]
    attempts: int
    raw: str


def strip_code_fences(text: str) -> str:
    """Return the body of the first markdown code fence, or *text* unchanged."""
    match = _CODE_FENCE_RE.search(text)
    return match.group(1).strip() if match else text


def json_object_candidates(text: str) -> list[str]:
    """Candidate JSON-object substrings of *text*, best first.

    First the first balanced ``{...}`` found by a string-aware brace scan (braces
    inside JSON strings are ignored, escapes honoured), then the greedy
    first-``{``-to-last-``}`` span as a fallback. The string-aware scan keeps a
    ``}`` inside a rationale from truncating the candidate mid-string
    (docs/DECISIONS.md#adr-structured-output).
    """
    candidates: list[str] = []
    start = text.find("{")
    if start == -1:
        return candidates
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidates.append(text[start : index + 1])
                break
    greedy = _GREEDY_OBJECT_RE.search(text)
    if greedy is not None and greedy.group() not in candidates:
        candidates.append(greedy.group())
    return candidates


def _informative(exc: ValidationError) -> bool:
    return any(err["type"] != "json_invalid" for err in validation_error_details(exc))


def parse_structured(raw: str, model: type[T]) -> tuple[T, Literal[1, 2]]:
    """Validate *raw* as *model*: tier 1 directly, tier 2 from extracted candidates.

    Raises the most informative ``ValidationError`` seen (a field error beats
    "invalid JSON"), or ``ValueError`` when the reply holds no JSON object.
    """
    try:
        return model.model_validate_json(raw), 1
    except ValidationError as exc:
        best: ValidationError = exc
    cleaned = strip_code_fences(raw)
    texts = [cleaned, *json_object_candidates(cleaned)]
    if cleaned != raw:
        texts.extend(json_object_candidates(raw))
    tried = {raw}
    for text in texts:
        if text in tried:
            continue
        tried.add(text)
        try:
            return model.model_validate_json(text), 2
        except ValidationError as exc:
            if _informative(exc) or not _informative(best):
                best = exc
    if not _informative(best) and not json_object_candidates(raw):
        raise ValueError("reply contains no JSON object")
    raise best


def _problems(exc: ValueError) -> list[str]:
    """One ``- <location>: <message>`` line per error, without input values or extra-key names."""
    if isinstance(exc, ValidationError):
        lines = [f"- {validation_error_location(err)}: {err['msg']}" for err in validation_error_details(exc)]
        return lines[:_MAX_ERRORS_SHOWN]
    return ["- (root): reply contains no JSON object"]


def _correction(problems: list[str]) -> str:
    return (
        "Your previous reply did not match the required JSON schema.\n"
        "Problems:\n" + "\n".join(problems) + "\n"
        "Reply again with exactly one JSON object that matches the schema. "
        "No prose, no code fences."
    )


async def chat_structured(
    provider: InferenceProvider,
    messages: list[InferenceMessage],
    model: type[T],
    *,
    retries: int = 1,
    temperature: float | None = None,
    max_tokens: int | None = None,
    schema: dict[str, Any] | None = None,
) -> StructuredResult[T]:
    """Ask *provider* for a reply that validates as *model*.

    ``schema`` overrides ``model.model_json_schema()`` (the advisory restricts
    tickers to an enum). Raises ``StructuredOutputError`` after ``retries + 1``
    invalid replies; provider exceptions propagate unchanged.
    """
    if retries < 0:
        raise ValueError("retries must be >= 0")
    response_schema = to_portable_schema(schema if schema is not None else model.model_json_schema())
    attempts = retries + 1
    conversation: list[InferenceMessage] = list(messages)
    for attempt in range(1, attempts + 1):
        result = await provider.chat(
            conversation,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = result.content or ""
        try:
            value, tier = parse_structured(raw, model)
        except ValueError as exc:
            problems = _problems(exc)
            log.warning(
                "structured_output_invalid",
                output_model=model.__name__,
                attempt=attempt,
                attempts=attempts,
                problem_count=len(problems),
            )
            if attempt < attempts:
                conversation = [*messages, {"role": "user", "content": _correction(problems)}]
            continue
        log.info(
            "structured_output_parsed",
            output_model=model.__name__,
            parse_tier=tier,
            attempts=attempt,
        )
        return StructuredResult(value=value, parse_tier=tier, attempts=attempt, raw=raw)
    log.warning("structured_output_failed", output_model=model.__name__, parse_tier=3, attempts=attempts)
    raise StructuredOutputError(
        f"{model.__name__}: no valid reply after {attempts} attempt(s)",
        provider=type(provider).__name__,
        model=provider.model,
        attempts=attempts,
    )
