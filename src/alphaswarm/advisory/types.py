"""ADVIS-01 boundary types — frozen pydantic models for the advisory JSON contract.

Pattern source: src/alphaswarm/ingestion/types.py (BaseModel(frozen=True, extra='forbid') + tuple[...]).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Signal = Literal["BUY", "SELL", "HOLD"]


class AdvisoryItem(BaseModel):
    """One ranked advisory recommendation per affected holding (D-06)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    consensus_signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_summary: str
    position_exposure: Decimal


class AdvisoryReport(BaseModel):
    """Top-level advisory payload written to advisory/{cycle_id}_advisory.json."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    generated_at: datetime
    portfolio_outlook: str
    items: tuple[AdvisoryItem, ...] = Field(default_factory=tuple)
    total_holdings: int
    affected_holdings: int
