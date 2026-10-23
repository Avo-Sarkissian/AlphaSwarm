"""Tests for the DataSourceAuditBuffer (ITEM 5 of quick task 260512-jqn)."""

from __future__ import annotations

import json

import pytest

from alphaswarm.data_audit import DataSourceAuditBuffer, DataSourceAuditEntry
from alphaswarm.state import StateStore
from alphaswarm.web.broadcaster import snapshot_to_json


def test_data_audit_entry_frozen() -> None:
    """DataSourceAuditEntry is an immutable frozen dataclass."""
    entry = DataSourceAuditEntry(
        ts=1700000000.0,
        source="yfinance",
        query="QQQX OHLCV",
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
    buf.record(source="yfinance", query="QQQX OHLCV", result="ok", used=True)
    snap = buf.snapshot()
    assert len(snap) == 1
    assert snap[0].source == "yfinance"
    assert snap[0].query == "QQQX OHLCV"
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
        source="yfinance",
        query="XQZW OHLCV",
        result="ok",
        used=True,
    )
    store.record_data_source(
        source="rss",
        query="headlines:XQZW",
        result="ok",
        used=False,
    )
    snap = store.snapshot()
    assert len(snap.data_source_audit) == 2
    assert snap.data_source_audit[0].source == "yfinance"
    assert snap.data_source_audit[1].source == "rss"

    # peek API is consistent with snapshot view.
    peek = store.peek_data_source_audit()
    assert peek == snap.data_source_audit


def test_data_audit_reaches_the_wire_frame() -> None:
    """The audit slice is mapped onto the WebSocket StateFrame."""
    store = StateStore()
    store.record_data_source(source="yfinance", query="ZZZT 1d OHLCV", result="ok", used=True)
    frame = json.loads(snapshot_to_json(store))
    assert len(frame["data_source_audit"]) == 1
    first = frame["data_source_audit"][0]
    assert (first["source"], first["query"], first["result"], first["used"]) == (
        "yfinance",
        "ZZZT 1d OHLCV",
        "ok",
        True,
    )
    assert isinstance(first["ts"], float)


def test_data_audit_empty_initially() -> None:
    """A fresh StateStore reports no audit entries on snapshot."""
    store = StateStore()
    snap = store.snapshot()
    assert snap.data_source_audit == ()
