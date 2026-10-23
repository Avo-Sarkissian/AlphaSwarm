"""Advisory types: the LLM-facing reply and the advisory the engine assembles.

``AdvisoryLLMOutput`` is the only thing the orchestrator writes: an outlook
plus conviction items. Totals, exposure, cycle id, timestamps, placeholders and
stats are computed server-side, so a formatting slip in a field the engine
would overwrite can no longer cost a retry (docs/DECISIONS.md#adr-advisory-pipeline).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaswarm.types import normalize_unit_interval

Signal = Literal["BUY", "SELL", "HOLD"]
ItemSource = Literal["swarm", "placeholder"]

_SPACES_RE: Final = re.compile(r"\s+")
_DOMINANCE_ORDER: Final[tuple[Signal, ...]] = ("SELL", "BUY", "HOLD")


def _one_line(value: str, max_chars: int) -> str:
    text = _SPACES_RE.sub(" ", value).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


class AdvisoryLLMItem(BaseModel):
    """One conviction item as the orchestrator writes it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # 32 covers every symbol a brokerage export can hold (OCC option symbols are 21
    # characters); the held-ticker enum in advisory_llm_schema is the real restriction.
    ticker: str = Field(min_length=1, max_length=32)
    signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    risk: str | None = None
    upside: str | None = None

    @field_validator("ticker", "signal", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> object:
        return normalize_unit_interval(value)

    @field_validator("rationale", mode="before")
    @classmethod
    def _rationale(cls, value: object) -> object:
        return _one_line(value, 500) if isinstance(value, str) else value

    @field_validator("risk", "upside", mode="before")
    @classmethod
    def _optional_line(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        text = _one_line(value, 300)
        return text or None


class AdvisoryLLMOutput(BaseModel):
    """The orchestrator's whole advisory reply."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    portfolio_outlook: str = Field(min_length=1)
    items: list[AdvisoryLLMItem] = Field(default_factory=list)

    @field_validator("portfolio_outlook", mode="before")
    @classmethod
    def _outlook(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdvisoryItem(BaseModel):
    """One holding in the assembled advisory (docs/DECISIONS.md#p41-d-06).

    ``source`` is ``"swarm"`` for a conviction item the orchestrator wrote and
    ``"placeholder"`` for the HOLD@0.30 padding the engine adds
    (docs/DECISIONS.md#sweep-b-7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    consensus_signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_summary: str
    position_exposure: Decimal
    source: ItemSource = "swarm"
    risk: str | None = None
    upside: str | None = None


class AdvisoryStats(BaseModel):
    """Overview numbers over conviction items only (placeholders excluded)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conviction_count: int = Field(ge=0)
    placeholder_count: int = Field(ge=0)
    buy_count: int = Field(ge=0)
    sell_count: int = Field(ge=0)
    hold_count: int = Field(ge=0)
    avg_confidence: float | None
    dominant_signal: Signal | None
    dominant_share: float | None

    @classmethod
    def from_items(cls, items: Sequence[AdvisoryItem]) -> AdvisoryStats:
        conviction = [item for item in items if item.source == "swarm"]
        counts = Counter(item.consensus_signal for item in conviction)
        # Stable sort: equal counts keep _DOMINANCE_ORDER, so ties go SELL > BUY > HOLD.
        ranked = sorted(_DOMINANCE_ORDER, key=lambda signal: -counts[signal])
        dominant = ranked[0] if conviction else None
        return cls(
            conviction_count=len(conviction),
            placeholder_count=len(items) - len(conviction),
            buy_count=counts["BUY"],
            sell_count=counts["SELL"],
            hold_count=counts["HOLD"],
            avg_confidence=(sum(item.confidence for item in conviction) / len(conviction) if conviction else None),
            dominant_signal=dominant,
            dominant_share=counts[dominant] / len(conviction) if dominant is not None else None,
        )


class AdvisoryReport(BaseModel):
    """Advisory payload written to ``advisory/{cycle_id}_advisory.json``.

    ``stats`` and ``holdings_as_of`` are ``None`` only in files written before
    they existed; the GET route still validates those files.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    generated_at: datetime
    portfolio_outlook: str
    items: tuple[AdvisoryItem, ...] = Field(default_factory=tuple)
    total_holdings: int
    affected_holdings: int
    stats: AdvisoryStats | None = None
    holdings_as_of: datetime | None = None
