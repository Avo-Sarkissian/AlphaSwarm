"""Tests for the DataSourceAuditBuffer (ITEM 5 of quick task 260512-jqn)."""
from __future__ import annotations

import dataclasses

import pytest

from alphaswarm.data_audit import DataSourceAuditBuffer, DataSourceAuditEntry
from alphaswarm.state import StateStore


def test_data_audit_entry_frozen() -> None:
    """DataSourceAuditEntry is an immutable frozen dataclass."""
    entry = DataSourceAuditEntry(
        ts=1700000000.0,
        source="yfinance",
        query="AAPL OHLCV",
        result="ok",
        used=True,
    )
    assert entry.source == "yfinance"
    assert entry.used is True
    with pytest.raises(AttributeError):
        entry.source = "fred"  # type: ignore[misc]


def test_data_audit_buffer_record_appends() -> None:
    """record() appends an entry to the buffer."""
    buf = DataSourceAuditBuffer()
    buf.record(source="yfinance", query="AAPL OHLCV", result="ok", used=True)
    snap = buf.snapshot()
    assert len(snap) == 1
    assert snap[0].source == "yfinance"
    assert snap[0].query == "AAPL OHLCV"
    assert snap[0].result == "ok"
    assert snap[0].used is True
    assert snap[0].ts > 0


def test_data_audit_buffer_caps_at_max_entries() -> None:
    """Pushing more than max_entries drops the oldest entries."""
    buf = DataSourceAuditBuffer(max_entries=3)
    for i in range(5):
        buf.record(
            source="yfinance",
            query=f"q{i}",
            result="ok",
            used=False,
        )
    snap = buf.snapshot()
    assert len(snap) == 3
    # Oldest two (q0, q1) dropped; q2..q4 retained in insertion order.
    queries = [e.query for e in snap]
    assert queries == ["q2", "q3", "q4"]


def test_data_audit_snapshot_returns_tuple() -> None:
    """snapshot() returns an immutable tuple, not the underlying deque."""
    buf = DataSourceAuditBuffer()
    buf.record(source="rss", query="entity", result="ok")
    snap = buf.snapshot()
    assert isinstance(snap, tuple)


def test_data_audit_refuses_to_log_secrets() -> None:
    """Defensive: record() refuses to log obvious secret patterns
    (threat T-260512-jqn-03)."""
    buf = DataSourceAuditBuffer()
    with pytest.raises(ValueError):
        buf.record(source="yfinance", query="x", result="error: sk-abc123")
    with pytest.raises(ValueError):
        buf.record(source="yfinance", query="x", result="API_KEY=secret123")
    with pytest.raises(ValueError):
        buf.record(source="yfinance", query="x", result="Bearer eyJ...")


def test_state_store_record_data_source_threading() -> None:
    """StateStore.record_data_source threads through to the audit buffer
    and the resulting entries surface in snapshot().data_source_audit."""
    store = StateStore()
    store.record_data_source(
        source="yfinance", query="NVDA OHLCV", result="ok", used=True,
    )
    store.record_data_source(
        source="rss", query="headlines:NVDA", result="ok", used=False,
    )
    snap = store.snapshot()
    assert len(snap.data_source_audit) == 2
    assert snap.data_source_audit[0].source == "yfinance"
    assert snap.data_source_audit[1].source == "rss"

    # peek API is consistent with snapshot view.
    peek = store.peek_data_source_audit()
    assert peek == snap.data_source_audit


def test_data_audit_serializes_through_dataclasses_asdict() -> None:
    """dataclasses.asdict (used by broadcaster.py) preserves data_source_audit."""
    store = StateStore()
    store.record_data_source(
        source="yfinance", query="AAPL OHLCV", result="ok", used=True,
    )
    snap = store.snapshot()
    d = dataclasses.asdict(snap)
    assert "data_source_audit" in d
    # dataclasses.asdict preserves the tuple container but converts each
    # nested DataSourceAuditEntry into a dict — that's the shape the
    # broadcaster json.dumps()s (json handles both tuples and lists).
    assert len(d["data_source_audit"]) == 1
    first = d["data_source_audit"][0]
    assert isinstance(first, dict)
    assert first["source"] == "yfinance"
    assert first["query"] == "AAPL OHLCV"


def test_data_audit_empty_initially() -> None:
    """A fresh StateStore reports no audit entries on snapshot."""
    store = StateStore()
    snap = store.snapshot()
    assert snap.data_source_audit == ()
