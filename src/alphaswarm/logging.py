"""Structured logging configuration for AlphaSwarm.

Phase 37 additions (ISOL-04):
  - pii_redaction_processor: recursive, variant-tolerant, free-text-scoped redaction
  - Fail-closed semantics (D-07): on processor exception, emit marker via
    sys.stderr bypass + DropEvent — no risk of re-entering the structlog chain.

Critical ordering (Pitfall 1): redaction MUST precede the terminal renderer.
After JSONRenderer/ConsoleRenderer runs, event_dict is a string — redaction
operating on a string is brittle and loses nested structure.

REVIEW REVISION (2026-04-18):
  - HIGH: recursive walker for nested dicts/lists/tuples/sets with cycle+depth
    protection (Codex)
  - HIGH: fail-closed uses a direct sys.stderr JSON write (safety-logger bypass),
    not re-entering structlog — eliminates recursion risk if PII processor is
    itself what's broken (Codex)
  - HIGH/MEDIUM: case-insensitive + separator-stripped key normalization —
    'costBasis', 'cost_basis', 'Cost-Basis', 'COSTBASIS', 'positions_by_account'
    all match the same path (Codex + Gemini)
  - MEDIUM: currency/SSN regex backstop is scoped to free-text keys only —
    prevents over-redaction of legitimate market prices (Codex)
  - MEDIUM: 'account_number_hash' is passed through unchanged — no double-hash
    destroying the correlation invariant (Codex)

Phase 37 / Task 17 additions (API key redaction):
  _LITERAL_NORMALIZED extended with API credential keys:
    apikey, apikeys, authorization, bearertoken, accesstoken,
    secretkey, orchestratorkey, workerkey.
  Covers RoleConfig.api_key, HTTP Authorization headers, and the spec's
  orchestrator_key/worker_key naming variants. Bare "token" is deliberately
  excluded (too broad — would clobber unrelated fields like "next_page_token").

Phase 3 (2026-10): API-key shapes (sk-…, nvapi-…, Bearer …) are scrubbed from
every string value at any depth, whatever its key.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from pydantic import ValidationError
from pydantic_core import ErrorDetails
from structlog.tracebacks import ExceptionDictTransformer

from alphaswarm.security.hashing import sha256_first8

# ------ Redaction constants (D-05 + D-06 + REVIEW HIGH/MEDIUM) ------

# REVIEW HIGH: key matching is case-insensitive and separator-agnostic.
# _normalize_key lowercases and strips _, -, and whitespace so these all match:
#   costBasis, cost_basis, Cost-Basis, COSTBASIS, "cost basis"
_LITERAL_NORMALIZED: frozenset[str] = frozenset(
    {
        # Portfolio / holdings PII (Phase 37)
        "holdings",
        "portfolio",
        "positions",
        "costbasis",
        "qty",
        "shares",
        "positionsbyaccount",
        "holdingsbyaccount",
        "portfoliobyaccount",
        # API credentials (Task 17) — normalized forms (lowercase, separators stripped)
        # Covers: api_key, apiKey, API-KEY → "apikey"
        #         Authorization, authorization → "authorization"
        #         bearer_token, Bearer-Token → "bearertoken"
        #         access_token, AccessToken → "accesstoken"
        #         secret_key, SecretKey → "secretkey"
        #         orchestrator_key, OrchestratorKey → "orchestratorkey"
        #         worker_key, WorkerKey → "workerkey"
        # Bare "token" is NOT included — too broad (would clobber next_page_token etc.)
        "apikey",
        "apikeys",
        "authorization",
        "bearertoken",
        "accesstoken",
        "secretkey",
        "orchestratorkey",
        "workerkey",
    }
)
_HASHED_NORMALIZED: frozenset[str] = frozenset({"accountnumber", "accountid", "acctid", "acctnumber"})
# REVIEW MEDIUM: pre-hashed correlation tokens must NOT be re-hashed.
_PASSTHROUGH_NORMALIZED: frozenset[str] = frozenset({"accountnumberhash"})
# REVIEW MEDIUM: currency/SSN backstop only applies within known free-text keys,
# NOT blanket on all string values (would clobber MarketSlice price strings).
_FREE_TEXT_NORMALIZED: frozenset[str] = frozenset({"note", "summary", "message", "text", "description", "reason"})

_CURRENCY_RE = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# API-key shapes are scrubbed from EVERY string value, whatever its key
# (docs/DECISIONS.md#adr-holdings-isolation): free-text error= fields and exception
# text can carry a token past the key-name rules. The patterns are vendor prefixes
# and "Bearer <token>", so ordinary text ("risk-adjusted", "task-123") is untouched.
_SECRET_TOKEN_RE = re.compile(
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{8,}"
    r"|\bnvapi-[A-Za-z0-9_\-]{8,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"
)
_SECRET_SENTINEL = "[REDACTED_SECRET]"

_MAX_REDACTION_DEPTH = 8
_CYCLE_SENTINEL = "[REDACTED_CYCLE]"
_DEPTH_SENTINEL = "[REDACTED_DEPTH]"


def _normalize_key(key: Any) -> str:
    """Lowercase + strip _, -, and spaces. Non-string keys return ''."""
    if not isinstance(key, str):
        return ""
    return re.sub(r"[\s_\-]+", "", key).lower()


def _hash_account(value: Any) -> str:
    """Hash account_* values to acct:<8-hex-chars>. Empty/None fall back to a fixed placeholder."""
    s = str(value) if value is not None else ""
    if s == "":
        return "acct:[EMPTY]"
    return f"acct:{sha256_first8(s)}"


def _scrub_secrets(s: str) -> str:
    return _SECRET_TOKEN_RE.sub(_SECRET_SENTINEL, s)


def _scrub_free_text(s: str) -> str:
    s = _CURRENCY_RE.sub("[REDACTED_CURRENCY]", s)
    s = _SSN_RE.sub("[REDACTED_SSN]", s)
    return s


def _redact_value(value: Any, *, depth: int, seen: set[int]) -> Any:
    """Recursively redact a value. Traverses dicts, lists, tuples, sets.

    REVIEW HIGH:
      - depth bounded at _MAX_REDACTION_DEPTH to prevent stack blowups
      - id()-seen-set prevents cycles in self-referential structures
    """
    if depth > _MAX_REDACTION_DEPTH:
        return _DEPTH_SENTINEL

    if isinstance(value, (dict, list, tuple, set)):
        vid = id(value)
        if vid in seen:
            return _CYCLE_SENTINEL
        seen.add(vid)
        try:
            if isinstance(value, dict):
                return _redact_mapping(value, depth=depth + 1, seen=seen)
            if isinstance(value, list):
                return [_redact_value(v, depth=depth + 1, seen=seen) for v in value]
            if isinstance(value, tuple):
                return tuple(_redact_value(v, depth=depth + 1, seen=seen) for v in value)
            if isinstance(value, set):
                return {_redact_value(v, depth=depth + 1, seen=seen) for v in value}
        finally:
            seen.discard(vid)

    # Scalar — scalars inside arbitrary (non-free-text) keys are passed through;
    # only mapping-level key rules decide redaction. Scalar-level scrubs happen
    # in _redact_mapping when the key matches _FREE_TEXT_NORMALIZED.
    # API-key shapes are the exception: they are scrubbed from every string.
    if isinstance(value, str):
        return _scrub_secrets(value)
    return value


def _redact_mapping(mapping: dict[Any, Any], *, depth: int, seen: set[int]) -> dict[Any, Any]:
    """Apply key-rule-based redaction to a single mapping level, recursing into children."""
    out: dict[Any, Any] = {}
    for key, value in mapping.items():
        norm = _normalize_key(key)

        if norm in _PASSTHROUGH_NORMALIZED:
            # REVIEW MEDIUM: pre-hashed token — pass through, do NOT re-hash
            out[key] = value
            continue

        if norm in _LITERAL_NORMALIZED:
            out[key] = "[REDACTED]"
            continue

        if norm in _HASHED_NORMALIZED:
            out[key] = _hash_account(value)
            continue

        # Not a sensitive key. If it's a free-text key, apply regex backstop to string.
        if norm in _FREE_TEXT_NORMALIZED and isinstance(value, str):
            out[key] = _scrub_free_text(_scrub_secrets(value))
            continue

        # Recurse into children so nested sensitive keys are caught.
        out[key] = _redact_value(value, depth=depth, seen=seen)
    return out


def _emit_redaction_failed_marker() -> None:
    """Side-channel marker emit (D-07 + REVIEW HIGH safety-logger bypass).

    Writes directly to sys.stderr as a single JSON line. Bypasses structlog
    entirely — cannot re-enter the PII processor that just failed.
    """
    try:
        sys.stderr.write(json.dumps({"event": "redaction_failed"}) + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 — last-resort side channel; nothing to do
        pass


def pii_redaction_processor(logger: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    """structlog processor implementing D-05/D-06/D-07 with review-mandated updates.

    - D-05: key-first detection (case-insensitive, separator-agnostic),
      free-text value-pattern backstop (scoped to note/summary/message/etc.)
    - D-06: account_* → sha256 hash; other sensitive keys → [REDACTED];
      account_number_hash → passthrough (REVIEW MEDIUM)
    - D-07: fail-closed — on any exception, emit marker via sys.stderr bypass
      (REVIEW HIGH safety-logger bypass) + drop event
    - REVIEW HIGH: recursive walk with cycle and depth protection
    """
    try:
        return _redact_mapping(dict(event_dict), depth=0, seen=set())
    except Exception:  # noqa: BLE001 — fail-closed by design
        _emit_redaction_failed_marker()
        raise structlog.DropEvent from None


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog for the application. Call once at startup.

    Args:
        log_level: Python log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON lines. If False, use colored console output.
    """
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,  # MUST be first processor
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    # Tracebacks never include local variables: frames hold API keys, prompts
    # and portfolio objects (docs/DECISIONS.md#adr-holdings-isolation). structlog's
    # stock dict_tracebacks and its default (Rich) console formatter both use
    # show_locals=True, so neither is used.
    if json_output:
        # Turn exc_info into a structured "exception" list before redaction, so
        # the redactor also walks the traceback. Without this, JSONRenderer only
        # emits "exc_info": true and the stack is lost.
        processors.append(structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)))
        processors.append(pii_redaction_processor)  # Phase 37 (ISOL-04): BEFORE renderer
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(pii_redaction_processor)  # Phase 37 (ISOL-04): BEFORE renderer
        processors.append(structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_bindings: object) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with optional initial context bindings."""
    return structlog.get_logger(**initial_bindings)  # type: ignore[no-any-return]


# ------ Loggable pydantic validation failures (docs/DECISIONS.md#adr-holdings-isolation) ------

_MAX_ERROR_LOCATIONS = 10


def validation_error_location(error: ErrorDetails) -> str:
    """Dotted location of one pydantic error. An extra key's own name is masked:
    it is text the model chose and could be a ticker."""
    parts = [str(part) for part in error["loc"]]
    if error["type"] == "extra_forbidden" and parts:
        parts[-1] = "<extra>"
    return ".".join(parts) or "(root)"


def validation_error_details(exc: ValidationError) -> list[ErrorDetails]:
    """The errors of *exc* without input values, URLs or context."""
    return exc.errors(include_input=False, include_url=False, include_context=False)


def _find_validation_error(exc: BaseException) -> ValidationError | None:
    """*exc* itself or the first pydantic ValidationError on its cause/context chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ValidationError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def validation_error_summary(exc: BaseException) -> dict[str, object]:
    """Loggable facts about the pydantic ValidationError *exc* is or was raised from.

    str() and repr() of a ValidationError echo the input values, which on the
    advisory path can include tickers or a cost basis. The summary keeps the error
    count, up to ten dotted locations and the sorted error types. Without a
    ValidationError on the chain it is {}: log the exception class (and, where
    safe, the traceback) instead. Callers that get a summary must not also pass
    exc_info, because the rendered traceback carries the exception text.
    """
    validation_error = _find_validation_error(exc)
    if validation_error is None:
        return {}
    errors = validation_error_details(validation_error)
    return {
        "error_count": len(errors),
        "error_locations": [validation_error_location(error) for error in errors[:_MAX_ERROR_LOCATIONS]],
        "error_types": sorted({error["type"] for error in errors}),
    }
