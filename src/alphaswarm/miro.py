"""Miro API batcher stub with data shape contracts (INFRA-10).

Defines Pydantic models for Miro REST API v2 payloads and a stub batcher
that logs instead of making HTTP calls. Per D-10: standalone module with
zero imports from alphaswarm.simulation or alphaswarm.graph. v2 replaces
log calls with httpx POST requests.

Data shapes based on Miro REST API v2:
- MiroNode: Board item (sticky note) representing an agent or bracket
- MiroConnector: Connector line between two board items (influence edges)
- MiroBatchPayload: Batch of nodes + connectors for a single API call
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


class MiroNode(BaseModel, frozen=True):
    """A board item (sticky note) representing an agent or bracket.

    Maps to Miro REST API v2 sticky note creation endpoint.
    """

    item_id: str                        # Agent ID or bracket name
    content: str                        # Display text (e.g., "BUY 0.85")
    color: str                          # Hex color based on sentiment
    x: float                            # Board position X
    y: float                            # Board position Y
    width: float = 200.0
    height: float = 200.0
    # Rev: [MEDIUM] Field(default_factory=dict) instead of mutable `= {}`
    metadata: dict[str, str | float] = Field(default_factory=dict)


class MiroConnector(BaseModel, frozen=True):
    """A connector line between two board items.

    Represents an INFLUENCED_BY edge between agents.
    Maps to Miro REST API v2 connector creation endpoint.
    """

    start_item_id: str                  # Source agent/bracket
    end_item_id: str                    # Target agent/bracket
    label: str = ""                     # Edge label (e.g., weight value)
    stroke_color: str = "#000000"
    stroke_width: float = 1.0


class MiroBatchPayload(BaseModel, frozen=True):
    """Batch of nodes and connectors for a single Miro API call.

    Groups visual updates into a single payload for the 2-second
    batching window (CLAUDE.md: strict 2-second buffer/batching).
    """

    board_id: str
    nodes: list[MiroNode]
    connectors: list[MiroConnector]
    # Rev: [LOW] Document ISO 8601 format requirement
    timestamp: str = Field(
        description="ISO 8601 formatted timestamp (e.g., '2026-03-26T12:00:00Z')"
    )


# ---------------------------------------------------------------------------
# Stub batcher
# ---------------------------------------------------------------------------


class MiroBatcher:
    """Stub batcher that defines the v2 Miro API contract (D-09).

    All methods log payloads via structlog instead of making HTTP calls.
    v2 replaces log calls with httpx POST requests to Miro REST API v2.

    Attributes:
        _board_id: Target Miro board ID.
        _buffer_seconds: Minimum seconds between API calls (2s per CLAUDE.md).
    """

    def __init__(self, board_id: str, buffer_seconds: float = 2.0) -> None:
        self._board_id = board_id
        self._buffer_seconds = buffer_seconds
        self._log = structlog.get_logger(component="miro")

    async def push_batch(self, payload: MiroBatchPayload) -> None:
        """Buffer and send a batch of nodes + connectors.

        v1: logs payload summary (counts only, not full payloads).
        v2: POST to Miro API with 2s buffer, bulk operations only.
        """
        # Rev: [LOW] Log counts only, not full serialized payloads (avoids noise)
        self._log.info(
            "miro_batch_stub",
            board_id=payload.board_id,
            node_count=len(payload.nodes),
            connector_count=len(payload.connectors),
            timestamp=payload.timestamp,
        )
