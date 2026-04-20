"""Shared fixtures for tests/invariants — sentinel constructors + surface capture stubs.

D-13: Sentinel constants are module-level so positive-control tests can import them.
D-15: Four capture surfaces are fixtures so the canary can assert absence across all of them.

REVIEW REVISION (2026-04-18):
- MEDIUM (Codex): `all_sentinel_representations()` helper returns every form
  a leaked sentinel may take after serialization — raw string, Decimal-string,
  JSON-quoted variants, sha256_first8 hash of account sentinel.
- LOW (Codex): Neo4j/WS/Jinja captures are pure in-memory lists, NO sockets.
- LOW (Gemini): json.dumps calls in canary use `default=str` for Decimal support.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import structlog

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.security.hashing import sha256_first8

# --------- D-13 sentinels (module-level; importable by positive controls) ---------

SENTINEL_TICKER = "SNTL_CANARY_TICKER"
SENTINEL_ACCT = "SNTL_CANARY_ACCT_000"
SENTINEL_COST_BASIS = Decimal("999999.99")
SENTINEL_QTY = Decimal("77.7777")


def all_sentinel_representations() -> tuple[str, ...]:
    """REVIEW MEDIUM (Codex): every form a sentinel might take after serialization.

    A leak might manifest as:
      - raw string (SNTL_CANARY_TICKER, SNTL_CANARY_ACCT_000)
      - Decimal stringified (999999.99, 77.7777)
      - Decimal JSON-serialized with default=str ("999999.99")
      - sha256_first8 of the account sentinel (PII processor hashes accounts)
    """
    acct_hash_short = sha256_first8(SENTINEL_ACCT)
    return (
        SENTINEL_TICKER,
        SENTINEL_ACCT,
        str(SENTINEL_COST_BASIS),  # "999999.99"
        str(SENTINEL_QTY),  # "77.7777"
        f'"{SENTINEL_COST_BASIS}"',  # JSON-quoted Decimal
        f'"{SENTINEL_QTY}"',
        acct_hash_short,  # post-hash form if redaction fires
    )


@pytest.fixture()
def sentinel_portfolio() -> PortfolioSnapshot:
    """D-13/D-14: a PortfolioSnapshot built with sentinel strings across every field.

    account_number_hash is overloaded in Phase 37 to hold the sentinel ACCT string
    directly — in production HOLD-02 hashes raw account numbers before this field
    is populated, but for canary greppability we stuff the sentinel here to ensure
    the test would catch even a direct hash-field leak.
    """
    holding = Holding(
        ticker=SENTINEL_TICKER,
        qty=SENTINEL_QTY,
        cost_basis=SENTINEL_COST_BASIS,
    )
    return PortfolioSnapshot(
        holdings=(holding,),
        as_of=datetime.now(UTC),
        account_number_hash=SENTINEL_ACCT,
    )


@pytest.fixture()
def capture_logs() -> io.StringIO:
    """Redirect structlog output to an in-memory buffer.

    Installs configure_logging() with json_output=True (triggers JSONRenderer after
    the PII redaction processor from Plan 03) and swaps the PrintLoggerFactory's
    target file to a StringIO. All structlog.get_logger().info(...) calls during
    the test land in the buffer, which the canary then greps.

    REVIEW LOW (Codex): pure in-memory, no file or socket.
    """
    buf = io.StringIO()

    class _BufferLogger:
        def msg(self, message: str) -> None:
            buf.write(message + "\n")

        def debug(self, message: str) -> None:
            self.msg(message)

        def info(self, message: str) -> None:
            self.msg(message)

        def warning(self, message: str) -> None:
            self.msg(message)

        def error(self, message: str) -> None:
            self.msg(message)

        def critical(self, message: str) -> None:
            self.msg(message)

    def _factory(*args: Any, **kwargs: Any) -> _BufferLogger:
        return _BufferLogger()

    from alphaswarm.logging import pii_redaction_processor

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            pii_redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG
        context_class=dict,
        logger_factory=_factory,  # type: ignore[arg-type]
        cache_logger_on_first_use=False,
    )
    return buf


@pytest.fixture()
def capture_ws_frames() -> list[str]:
    """In-memory list standing in for WebSocket broadcaster frames.

    REVIEW LOW (Codex): NO real ConnectionManager, no real socket.
    """
    return []


@pytest.fixture()
def capture_neo4j_writes() -> list[str]:
    """In-memory list standing in for Neo4j session writes.

    REVIEW LOW (Codex): NO real Neo4j driver, no bolt connection.
    """
    return []


@pytest.fixture()
def capture_jinja_renders() -> list[str]:
    """In-memory list standing in for worker prompt renders.

    At Phase 37 no worker prompt references holdings, so this stays empty.
    """
    return []


# ------------------------------------------------------------------
# Phase 41 D-20: canary Fakes used by the real-synthesize harness.
# These replace the Phase 37 `_minimal_simulation_body` stub with a
# load-bearing invariant: if `alphaswarm.advisory.synthesize` leaks
# sentinel values into any of the four surface sinks, the canary fails.
# ------------------------------------------------------------------
import json as _json_for_canary  # local alias to avoid shadowing
from typing import Any as _AnyForCanary


class CanaryFakeOllamaClient:
    """FakeOllamaClient that records every message into capture_jinja_renders.

    Pitfall 5: the LLM prompt IS surface #4 of the canary. The fake appends
    the full concatenated messages string so the canary can grep it for any
    sentinel representation.
    """

    def __init__(self, *, prompt_sink: list[str], canned_content: str) -> None:
        self._prompt_sink = prompt_sink
        self._canned = canned_content

    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.message = CanaryFakeOllamaClient._Msg(content)

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format: str | dict[str, _AnyForCanary] | None = None,
        **_: _AnyForCanary,
    ) -> "CanaryFakeOllamaClient._Resp":
        # Surface #4: record the rendered prompt for canary inspection.
        rendered = "\n".join(m.get("content", "") for m in messages)
        self._prompt_sink.append(rendered)
        return CanaryFakeOllamaClient._Resp(self._canned)


class CanaryFakeGraphManager:
    """FakeGraphManager that routes every read cycle_id into capture_neo4j_writes.

    Pitfall 5: surface #2 is the Neo4j layer. We treat the cycle_id the
    engine forwards as the "write" content so the canary observes whatever
    synthesize() decides to pass downstream. Returns empty payloads so the
    engine proceeds normally through its LLM call.
    """

    def __init__(self, *, neo4j_sink: list[str]) -> None:
        self._sink = neo4j_sink

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, _AnyForCanary]:
        self._sink.append(f"read_consensus_summary cycle_id={cycle_id}")
        return {"buy_count": 0, "sell_count": 0, "hold_count": 0, "total": 0}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, _AnyForCanary]]:
        self._sink.append(f"read_round_timeline cycle_id={cycle_id}")
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, _AnyForCanary]]:
        self._sink.append(f"read_bracket_narratives cycle_id={cycle_id}")
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, _AnyForCanary]]:
        self._sink.append(f"read_entity_impact cycle_id={cycle_id}")
        return []


def canary_valid_advisory_json() -> str:
    """A minimally valid AdvisoryReport JSON — no sentinel values inside."""
    return _json_for_canary.dumps({
        "cycle_id": "canary_cycle",
        "generated_at": "2026-04-19T22:00:00+00:00",
        "portfolio_outlook": "Canary outlook — no sentinels.",
        "items": [],
        "total_holdings": 1,
        "affected_holdings": 0,
    })
