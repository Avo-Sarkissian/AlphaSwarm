"""ISOL-04: PII redaction processor tests.

Tabular cases (D-05, D-06, D-07) + Hypothesis property-based fuzzing (D-08) +
positive-control test (Pitfall 6: prove capture machinery isn't trivially green).

REVIEW REVISION (2026-04-18):
- HIGH: nested recursion + cycle + depth tests
- HIGH: case-insensitive/variant key matching tests
- HIGH: fail-closed safety-logger bypass test (stderr capture)
- MEDIUM: account_number_hash passthrough (no double-hash)
- MEDIUM: free-text regex scoping (ordinary keys with '$' survive)
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import structlog
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from alphaswarm.logging import configure_logging, pii_redaction_processor

SENTINEL_TICKER = "SNTL_CANARY_TICKER"
SENTINEL_ACCT = "SNTL_CANARY_ACCT_000"


# --------- Direct processor unit tests (D-05, D-06) ---------


def test_processor_redacts_holdings_key_to_redacted_literal() -> None:
    result = pii_redaction_processor(None, "info", {"event": "x", "holdings": ["AAPL", "MSFT"]})
    assert result["holdings"] == "[REDACTED]"
    assert result["event"] == "x"


def test_processor_redacts_portfolio_cost_basis_qty_shares_positions() -> None:
    for key in ("portfolio", "cost_basis", "qty", "shares", "positions"):
        result = pii_redaction_processor(None, "info", {"event": "x", key: "SENSITIVE_VALUE"})
        assert result[key] == "[REDACTED]"


def test_processor_hashes_account_number_with_acct_prefix() -> None:
    result = pii_redaction_processor(None, "info", {"event": "x", "account_number": "1234567890"})
    assert result["account_number"].startswith("acct:")
    assert re.fullmatch(r"acct:[0-9a-f]{8}", result["account_number"]) is not None


def test_processor_hashes_account_id_with_acct_prefix() -> None:
    result = pii_redaction_processor(None, "info", {"event": "x", "account_id": "abc-123"})
    assert result["account_id"].startswith("acct:")


def test_processor_handles_empty_account_number() -> None:
    """sha256_first8 rejects empty strings (Pitfall 7); processor must handle it."""
    result = pii_redaction_processor(None, "info", {"event": "x", "account_number": ""})
    assert result["account_number"] == "acct:[EMPTY]"


# --------- REVIEW HIGH: case-insensitive + variant key matching ---------


@pytest.mark.parametrize(
    "variant_key",
    [
        "costBasis",
        "COST_BASIS",
        "Cost-Basis",
        "COSTBASIS",
        "cost basis",
        "HOLDINGS",
        "Holdings",
        "holdings",
    ],
)
def test_processor_matches_case_and_separator_variants(variant_key: str) -> None:
    """REVIEW HIGH (Codex+Gemini): redaction MUST match regardless of case or separators."""
    result = pii_redaction_processor(None, "info", {"event": "x", variant_key: "LEAK_ME"})
    assert result[variant_key] == "[REDACTED]"


def test_processor_matches_positions_by_account_variant() -> None:
    """REVIEW HIGH — 'positions_by_account' and 'positionsByAccount' both redacted."""
    for key in ("positions_by_account", "positionsByAccount", "Positions-By-Account"):
        result = pii_redaction_processor(None, "info", {"event": "x", key: {"AAPL": 100}})
        assert result[key] == "[REDACTED]"


@pytest.mark.parametrize("variant_key", ["acct_id", "acctId", "AcctNumber", "ACCT_NUMBER"])
def test_processor_hashes_account_variants(variant_key: str) -> None:
    result = pii_redaction_processor(None, "info", {"event": "x", variant_key: "1234567890"})
    assert result[variant_key].startswith("acct:")


# --------- REVIEW MEDIUM: account_number_hash passthrough ---------


def test_account_number_hash_is_not_rehashed() -> None:
    """REVIEW MEDIUM (Codex) — pre-hashed token must pass through unchanged,
    otherwise downstream correlation breaks ('acct:{hash(hash)}' is useless)."""
    prehashed = "acct:abcd1234"
    result = pii_redaction_processor(
        None, "info", {"event": "x", "account_number_hash": prehashed}
    )
    assert result["account_number_hash"] == prehashed  # passthrough
    # Also test case/separator variants of the hash key
    for key in ("AccountNumberHash", "account-number-hash", "accountnumberhash"):
        r = pii_redaction_processor(None, "info", {"event": "x", key: prehashed})
        assert r[key] == prehashed


# --------- REVIEW HIGH: recursive nested redaction ---------


def test_processor_recurses_into_nested_dict() -> None:
    """REVIEW HIGH (Codex) — top-level-only redaction would leak this."""
    event = {"event": "x", "payload": {"portfolio": ["AAPL", "MSFT"]}}
    result = pii_redaction_processor(None, "info", event)
    assert result["payload"]["portfolio"] == "[REDACTED]"


def test_processor_recurses_into_nested_list_of_dicts() -> None:
    event = {
        "event": "x",
        "agents": [
            {"id": "a1", "holdings": ["SECRET1"]},
            {"id": "a2", "holdings": ["SECRET2"]},
        ],
    }
    result = pii_redaction_processor(None, "info", event)
    assert result["agents"][0]["holdings"] == "[REDACTED]"
    assert result["agents"][1]["holdings"] == "[REDACTED]"


def test_processor_recurses_into_tuple() -> None:
    event = {"event": "x", "data": ({"costBasis": "100.00"},)}
    result = pii_redaction_processor(None, "info", event)
    assert result["data"][0]["costBasis"] == "[REDACTED]"


def test_processor_handles_cycles_without_stack_overflow() -> None:
    """REVIEW HIGH (Codex) — cycle detection via id() seen-set."""
    cyclic: dict[str, Any] = {"event": "x"}
    cyclic["self"] = cyclic
    # Must not raise RecursionError
    result = pii_redaction_processor(None, "info", cyclic)
    # Cycle should be replaced with sentinel at some level
    rendered = json.dumps(result, default=str)
    assert "[REDACTED_CYCLE]" in rendered


def test_processor_honors_max_depth() -> None:
    """REVIEW HIGH — bounded recursion prevents DoS via deeply nested payloads."""
    # Build nested dict 20 levels deep
    leaf: dict[str, Any] = {"holdings": ["SECRET_LEAK"]}
    nested: Any = leaf
    for _ in range(20):
        nested = {"next": nested}
    result = pii_redaction_processor(None, "info", {"event": "x", "tree": nested})
    rendered = json.dumps(result, default=str)
    # Even if depth cuts off recursion, the sensitive literal must never appear verbatim
    assert "SECRET_LEAK" not in rendered


# --------- REVIEW MEDIUM: free-text scoping ---------


def test_processor_scrubs_currency_pattern_in_free_text_key() -> None:
    result = pii_redaction_processor(
        None, "info", {"event": "x", "note": "Client paid $12,345.67 last week"}
    )
    assert "$12,345.67" not in result["note"]
    assert "[REDACTED_CURRENCY]" in result["note"]


def test_processor_scrubs_ssn_pattern_in_free_text_key() -> None:
    result = pii_redaction_processor(
        None, "info", {"event": "x", "summary": "SSN 123-45-6789 on file"}
    )
    assert "123-45-6789" not in result["summary"]
    assert "[REDACTED_SSN]" in result["summary"]


def test_processor_does_NOT_scrub_currency_in_non_free_text_key() -> None:
    """REVIEW MEDIUM (Codex) — scrubbing every string clobbers ordinary market prices.

    A MarketSlice diagnostic event might log {'ticker': 'AAPL', 'price_display': '$185.50'};
    price_display is NOT a free-text key, must be preserved verbatim."""
    result = pii_redaction_processor(
        None, "info", {"event": "price_log", "price_display": "$185.50"}
    )
    assert result["price_display"] == "$185.50"  # NOT redacted


def test_processor_does_not_scrub_sensitive_keys_via_value_pass() -> None:
    """account_number goes through the hash path, not the value-scrub pass."""
    result = pii_redaction_processor(
        None, "info", {"event": "x", "account_number": "$999.00"}
    )
    assert result["account_number"].startswith("acct:")  # hashed, not currency-scrubbed


# --------- REVIEW HIGH: fail-closed safety-logger bypass (D-07) ---------


def test_processor_fails_closed_on_internal_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """If sha256_first8 misbehaves, processor must DropEvent AND emit a marker
    via sys.stderr bypass (REVIEW HIGH — Codex fail-closed recursion avoidance)."""
    import alphaswarm.logging as logmod

    def broken(_: str) -> str:
        raise RuntimeError("simulated hash failure")

    monkeypatch.setattr(logmod, "sha256_first8", broken)

    with pytest.raises(structlog.DropEvent):
        pii_redaction_processor(None, "info", {"event": "x", "account_number": "real"})

    captured = capsys.readouterr()
    # Marker emitted to stderr as single JSON line (NOT via structlog chain)
    assert "redaction_failed" in captured.err


def test_safety_marker_bypasses_structlog_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """REVIEW HIGH — the marker write path must not re-enter pii_redaction_processor.

    If marker emission ran the marker event back through the processor, a
    bug inside the processor would recurse infinitely. We verify the marker
    path writes to sys.stderr directly (not via structlog)."""
    import alphaswarm.logging as logmod

    # Force a failure inside the (real) processor
    monkeypatch.setattr(
        logmod,
        "sha256_first8",
        lambda _s: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(structlog.DropEvent):
        pii_redaction_processor(None, "info", {"event": "x", "account_number": "r"})

    captured = capsys.readouterr()
    assert "redaction_failed" in captured.err


# --------- Integration via configure_logging (chain ordering) ---------


def test_processor_runs_before_renderer_in_configured_chain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Positive control (Pitfall 6): capture machinery sees [REDACTED], not raw value."""
    configure_logging(log_level="INFO", json_output=True)
    logger = structlog.get_logger()
    logger.info("test_event", holdings=[SENTINEL_TICKER])

    captured = capsys.readouterr()
    # Negative assertion (the canary invariant):
    assert SENTINEL_TICKER not in captured.out
    # Positive assertion (Pitfall 6 — prove capture actually captures):
    assert "[REDACTED]" in captured.out


def test_nested_sentinel_is_redacted_through_configured_chain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REVIEW HIGH — end-to-end nested redaction through the real structlog chain."""
    configure_logging(log_level="INFO", json_output=True)
    logger = structlog.get_logger()
    logger.info("nested_event", payload={"portfolio": [SENTINEL_TICKER]})

    captured = capsys.readouterr()
    assert SENTINEL_TICKER not in captured.out
    assert "[REDACTED]" in captured.out


def test_account_number_rendered_as_acct_hash(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_level="INFO", json_output=True)
    logger = structlog.get_logger()
    logger.info("account_event", account_number="1234567890")

    captured = capsys.readouterr()
    assert "1234567890" not in captured.out
    assert re.search(r"acct:[0-9a-f]{8}", captured.out) is not None


# --------- Hypothesis fuzz (D-08) over NESTED variant-case payloads ---------


_SENSITIVE_KEY_VARIANTS = st.sampled_from(
    [
        "holdings",
        "HOLDINGS",
        "Holdings",
        "portfolio",
        "Portfolio",
        "positions",
        "Positions",
        "positions_by_account",
        "positionsByAccount",
        "cost_basis",
        "costBasis",
        "CostBasis",
        "COSTBASIS",
        "qty",
        "QTY",
        "shares",
        "Shares",
    ]
)
def _normalize_safe(s: str) -> bool:
    """Filter out accidental matches with sensitive-normalized keys."""
    blacklist = {
        "holdings",
        "portfolio",
        "positions",
        "costbasis",
        "qty",
        "shares",
        "accountnumber",
        "accountid",
        "acctid",
        "acctnumber",
        "accountnumberhash",
        "note",
        "summary",
        "message",
        "text",
        "description",
        "reason",
        "event",
        "positionsbyaccount",
        "holdingsbyaccount",
        "portfoliobyaccount",
    }
    return s.lower() not in blacklist


_SAFE_KEY_STRATEGY = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)), min_size=3, max_size=10
).filter(_normalize_safe)


# Sensitive values use a fixed prefix so they are distinguishable from key names in
# rendered JSON — avoids false positives where a short value appears as a substring
# of a key name (e.g., value='aa' inside key 'aaa').
_VALUE_STRATEGY = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=6, max_size=30
).map(lambda s: f"SVAL_{s}")


def _nested_sensitive_strategy() -> Any:
    """Build a nested dict up to 3 levels with mixed sensitive/safe keys."""
    return st.recursive(
        st.dictionaries(
            _SENSITIVE_KEY_VARIANTS, _VALUE_STRATEGY, min_size=1, max_size=3
        ),
        lambda children: st.dictionaries(_SAFE_KEY_STRATEGY, children, min_size=1, max_size=3),
        max_leaves=8,
    )


@given(payload=_nested_sensitive_strategy())
@settings(max_examples=150, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
def test_fuzz_no_sensitive_value_renders_verbatim_nested(payload: dict[str, Any]) -> None:
    """D-08 + REVIEW HIGH: sensitive values must not leak verbatim at any nesting depth."""
    # Collect all sensitive-key leaf values (at any depth)
    sensitive_values: list[str] = []

    def _collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and re.sub(r"[\s_\-]+", "", k).lower() in {
                    "holdings",
                    "portfolio",
                    "positions",
                    "costbasis",
                    "qty",
                    "shares",
                    "positionsbyaccount",
                    "holdingsbyaccount",
                    "portfoliobyaccount",
                }:
                    if isinstance(v, str):
                        sensitive_values.append(v)
                    else:
                        _collect(v)
                else:
                    _collect(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _collect(item)

    _collect(payload)

    event_dict: dict[str, Any] = {"event": "fuzz", "payload": payload}
    result = pii_redaction_processor(None, "info", dict(event_dict))
    rendered = json.dumps(result, default=str)

    for v in sensitive_values:
        if v == "":
            continue
        assert v not in rendered, f"Sensitive value {v!r} leaked verbatim into rendered output"


# --------- Tabular regression cases ---------


@pytest.mark.parametrize(
    "event_dict,banned_substrings",
    [
        ({"event": "x", "holdings": ["AAPL"]}, ["AAPL"]),
        ({"event": "x", "cost_basis": "150.25"}, ["150.25"]),
        ({"event": "x", "costBasis": "150.25"}, ["150.25"]),  # variant case
        ({"event": "x", "account_number": "ACC-999"}, ["ACC-999"]),
        ({"event": "x", "note": "paid $99,999.99"}, ["$99,999.99"]),
        ({"event": "x", "summary": "SSN 555-66-7777"}, ["555-66-7777"]),
        (
            {"event": "x", "payload": {"portfolio": ["NESTED_LEAK"]}},
            ["NESTED_LEAK"],
        ),
        (
            {"event": "x", "agents": [{"holdings": ["LEAK_IN_LIST"]}]},
            ["LEAK_IN_LIST"],
        ),
    ],
)
def test_tabular_no_sensitive_leaks(
    event_dict: dict[str, Any], banned_substrings: list[str]
) -> None:
    result = pii_redaction_processor(None, "info", dict(event_dict))
    rendered = json.dumps(result, default=str)
    for banned in banned_substrings:
        assert banned not in rendered
