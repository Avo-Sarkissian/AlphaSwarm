"""Unit tests for Miro API batcher stub and data shapes (INFRA-10)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_miro_node_model() -> None:
    """MiroNode creates with required fields and is frozen."""
    from alphaswarm.miro import MiroNode

    node = MiroNode(
        item_id="quants_01",
        content="BUY 0.85",
        color="#00FF00",
        x=100.0,
        y=200.0,
    )
    assert node.item_id == "quants_01"
    assert node.content == "BUY 0.85"
    assert node.color == "#00FF00"
    assert node.x == 100.0
    assert node.y == 200.0

    with pytest.raises(ValidationError):
        node.item_id = "changed"  # type: ignore[misc]


def test_miro_node_defaults() -> None:
    """MiroNode has correct default values for optional fields."""
    from alphaswarm.miro import MiroNode

    node = MiroNode(item_id="a", content="t", color="#FFF", x=0.0, y=0.0)
    assert node.width == 200.0
    assert node.height == 200.0
    assert node.metadata == {}


def test_miro_node_metadata_not_shared() -> None:
    """Two MiroNode instances with default metadata do not share the same dict.

    Rev: [MEDIUM] Verifies Field(default_factory=dict) is used, not mutable `= {}`.
    """
    from alphaswarm.miro import MiroNode

    node1 = MiroNode(item_id="a", content="t", color="#FFF", x=0.0, y=0.0)
    node2 = MiroNode(item_id="b", content="t", color="#FFF", x=1.0, y=1.0)
    # Default metadata dicts must be independent instances
    assert node1.metadata is not node2.metadata


def test_miro_connector_model() -> None:
    """MiroConnector creates with required fields and has defaults."""
    from alphaswarm.miro import MiroConnector

    conn = MiroConnector(start_item_id="quants_01", end_item_id="degens_01")
    assert conn.start_item_id == "quants_01"
    assert conn.end_item_id == "degens_01"
    assert conn.label == ""
    assert conn.stroke_color == "#000000"
    assert conn.stroke_width == 1.0


def test_miro_batch_payload_model() -> None:
    """MiroBatchPayload bundles nodes and connectors."""
    from alphaswarm.miro import MiroBatchPayload, MiroConnector, MiroNode

    node = MiroNode(item_id="a", content="t", color="#FFF", x=0.0, y=0.0)
    conn = MiroConnector(start_item_id="a", end_item_id="b")
    payload = MiroBatchPayload(
        board_id="test-board",
        nodes=[node],
        connectors=[conn],
        timestamp="2026-03-26T00:00:00Z",
    )
    assert payload.board_id == "test-board"
    assert len(payload.nodes) == 1
    assert len(payload.connectors) == 1
    assert payload.timestamp == "2026-03-26T00:00:00Z"


def test_miro_batch_payload_serialization() -> None:
    """MiroBatchPayload.model_dump() returns correct dict structure."""
    from alphaswarm.miro import MiroBatchPayload, MiroConnector, MiroNode

    node = MiroNode(item_id="a", content="t", color="#FFF", x=0.0, y=0.0)
    conn = MiroConnector(start_item_id="a", end_item_id="b")
    payload = MiroBatchPayload(
        board_id="board-1",
        nodes=[node],
        connectors=[conn],
        timestamp="2026-03-26T00:00:00Z",
    )
    dumped = payload.model_dump()
    assert "board_id" in dumped
    assert "nodes" in dumped
    assert "connectors" in dumped
    assert "timestamp" in dumped
    assert isinstance(dumped["nodes"], list)
    assert isinstance(dumped["nodes"][0], dict)


@pytest.mark.asyncio()
async def test_miro_batcher_logs_payload() -> None:
    """MiroBatcher.push_batch logs payload summary without HTTP calls."""
    from alphaswarm.miro import MiroBatchPayload, MiroConnector, MiroNode, MiroBatcher

    node = MiroNode(item_id="a", content="t", color="#FFF", x=0.0, y=0.0)
    conn = MiroConnector(start_item_id="a", end_item_id="b")
    payload = MiroBatchPayload(
        board_id="test-board",
        nodes=[node],
        connectors=[conn],
        timestamp="2026-03-26T00:00:00Z",
    )

    batcher = MiroBatcher("test-board")
    # Should complete without error (logs internally)
    await batcher.push_batch(payload)
    # No exception = success. The stub logs, not sends HTTP.


def test_miro_batcher_buffer_config() -> None:
    """MiroBatcher default buffer_seconds is 2.0."""
    from alphaswarm.miro import MiroBatcher

    batcher = MiroBatcher("board-1")
    assert batcher._buffer_seconds == 2.0


def test_miro_batcher_custom_buffer() -> None:
    """MiroBatcher accepts custom buffer_seconds."""
    from alphaswarm.miro import MiroBatcher

    batcher = MiroBatcher("board-1", buffer_seconds=5.0)
    assert batcher._buffer_seconds == 5.0


def test_miro_module_no_simulation_imports() -> None:
    """miro.py does not import from alphaswarm.simulation or alphaswarm.graph (D-10)."""
    miro_path = Path(__file__).parent.parent / "src" / "alphaswarm" / "miro.py"
    source = miro_path.read_text()
    tree = ast.parse(source)

    forbidden = {"alphaswarm.simulation", "alphaswarm.graph"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden, (
                f"miro.py imports from {node.module} -- violates D-10 standalone constraint"
            )
