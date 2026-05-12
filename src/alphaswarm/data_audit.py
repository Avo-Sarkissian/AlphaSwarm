"""Bounded audit log for data-provider calls (ITEM 5 of quick task 260512-jqn).

Each call into a market/news provider (yfinance, FRED, RSS, etc.) appends one
DataSourceAuditEntry to a deque(maxlen=100). The buffer is read once per
~5Hz tick by the WS broadcaster so the SignalWire ticker shows real live
provider activity instead of the DEV mock seed.

Design notes:
    • In-memory only. No persistence. This is an observability tool, not
      a compliance trail (see threat T-260512-jqn-09).
    • record() is O(1) and lock-free — safe to call from any context,
      sync or async.
    • result/query/source are short summary strings. Providers MUST NEVER
      pass raw response bodies or env-vars (threat T-260512-jqn-03).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class DataSourceAuditEntry:
    """Single immutable provider-call audit record.

    Attributes:
        ts: Wall-clock timestamp of the call (seconds since epoch).
        source: Provider identifier — 'yfinance' | 'fred' | 'rss' | etc.
        query: Human-readable query summary (e.g. 'AAPL 1d OHLCV').
        result: Short status — 'ok' | 'cached' | 'error: <short msg>' |
                '<n_bytes>'. MUST NOT contain raw response data or secrets.
        used: True if the result fed into a worker prompt; False if it was
              fetched but unused (cache fill, prefetch, etc.).
    """

    ts: float
    source: str
    query: str
    result: str
    used: bool


class DataSourceAuditBuffer:
    """Bounded audit log for data-provider calls.

    The deque silently drops the oldest entry when capacity is reached, so the
    record() call is O(1) and never blocks. A single buffer lives on
    StateStore.

    Typical usage from a provider module:

        state_store.record_data_source(
            source='yfinance',
            query=f'{ticker} 1d OHLCV',
            result='ok' if data else 'error: empty',
            used=True,
        )

    The WS broadcaster reads the buffer via snapshot() once per tick.
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._buf: deque[DataSourceAuditEntry] = deque(maxlen=max_entries)

    def record(
        self,
        source: str,
        query: str,
        result: str,
        used: bool = False,
    ) -> None:
        """Append a single audit record. Drops oldest if buffer is full.

        Args:
            source: Provider identifier (short string).
            query: Human-readable query summary.
            result: Short status string ('ok'/'cached'/'error: <msg>').
            used: True if the call fed into a worker prompt.

        Raises:
            ValueError: If `result` contains an obvious secret pattern
                (defensive, threat T-260512-jqn-03).
        """
        # Defensive: refuse obvious secret leaks. Cheap substring check —
        # providers SHOULD never reach this guard in normal use.
        lowered = result.lower()
        if "sk-" in lowered or "api_key=" in lowered or "bearer " in lowered:
            raise ValueError(
                "DataSourceAuditBuffer.record refuses to log a secret-looking string"
            )
        self._buf.append(
            DataSourceAuditEntry(
                ts=time.time(),
                source=source,
                query=query,
                result=result,
                used=used,
            )
        )

    def snapshot(self) -> tuple[DataSourceAuditEntry, ...]:
        """Return the full buffer as an immutable tuple (oldest → newest)."""
        return tuple(self._buf)

    def __len__(self) -> int:
        return len(self._buf)
