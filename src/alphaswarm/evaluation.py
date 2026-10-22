"""Point-in-time evaluation: records, outcome labels and forecast scoring (P7.7, P7.8).

Pure functions plus small synchronous file helpers: no network, no Neo4j, no event
loop. The scripts under the repo-root ``eval/`` directory fetch prices, launch runs
and read cycles; every constant here is pre-registered before any evaluation run
(docs/DECISIONS.md#adr-eval-harness). Callers inside an event loop wrap the file
helpers in ``asyncio.to_thread``.
"""

from __future__ import annotations

import math
import os
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from statistics import stdev
from typing import Final, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from alphaswarm.types import AgentDecision, BracketConfig, SignalType

EventCategory = Literal[
    "m_and_a",
    "earnings",
    "guidance",
    "regulatory",
    "macro",
    "product",
    "management",
    "capital_allocation",
    "litigation",
    "other",
]
Variant = Literal["named", "anon"]
Direction = Literal["up", "down", "flat"]
Horizon = Literal["1d", "5d"]
BaselineKind = Literal["single_k5", "self_consistency"]
ProbeDirection = Literal["up", "down", "flat", "unknown"]

TICKER_PATTERN: Final = r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$"
EVENT_ID_PATTERN: Final = r"^evt-\d{3}$"
SEED_BASE: Final = 2100
EVAL_SEEDS: Final[tuple[int, ...]] = (1, 2, 3)
EVAL_NUM_ROUNDS: Final = 2
ABLATION_SUBSET_SIZE: Final = 5
MIN_EVENTS: Final = 15
MAX_EVENTS: Final = 20
MIN_POST_CUTOFF_SHARE: Final = 0.4
BOOT_SEED: Final = 20261003

_FROZEN: Final = ConfigDict(frozen=True, extra="forbid")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must carry a timezone, e.g. 2026-08-14T13:30:00Z")
    return value.astimezone(UTC)


class EvalEvent(BaseModel):
    """One line of ``eval/events.jsonl`` (the eval event file format)."""

    model_config = _FROZEN

    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    timestamp: datetime
    rumor: str = Field(min_length=10, max_length=2000)
    primary_ticker: str = Field(pattern=TICKER_PATTERN)
    benchmark: str = Field(default="SPY", pattern=TICKER_PATTERN)
    category: EventCategory
    post_cutoff: bool
    anonymized_rumor: str = Field(min_length=10, max_length=2000)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_in_utc(cls, value: datetime) -> datetime:
        return _to_utc(value)

    def rumor_for(self, variant: Variant) -> str:
        return self.rumor if variant == "named" else self.anonymized_rumor


class OutcomeLabel(BaseModel):
    """One line of ``eval/results/labels.jsonl`` (the outcome label file format)."""

    model_config = _FROZEN

    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    abn_ret_1d: float
    abn_ret_5d: float
    vol_scale: float = Field(gt=0.0)
    label_1d: Direction
    label_5d: Direction

    def label(self, horizon: Horizon) -> Direction:
        return self.label_1d if horizon == "1d" else self.label_5d

    def abn_ret(self, horizon: Horizon) -> float:
        return self.abn_ret_1d if horizon == "1d" else self.abn_ret_5d


class FixtureHeadline(BaseModel):
    """One curated line of ``eval/headlines/<event_id>.jsonl``."""

    model_config = _FROZEN

    published_at: datetime
    title: str = Field(min_length=1, max_length=300)

    @field_validator("published_at")
    @classmethod
    def _published_in_utc(cls, value: datetime) -> datetime:
        return _to_utc(value)


class BaselineRecord(BaseModel):
    """One finished baseline unit (event, variant, seed) in ``baselines.jsonl``."""

    model_config = _FROZEN

    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    variant: Variant
    kind: BaselineKind
    seed: int = Field(ge=1)
    k: int = Field(ge=1)
    n_valid: int = Field(ge=0)
    score: float = Field(ge=-1.0, le=1.0)
    model: str
    created_at: datetime


class ProbeAnswer(BaseModel):
    """What the worker says it remembers about an event (LLM-facing; extra keys ignored)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    recalled: bool
    direction: ProbeDirection
    rationale: str = ""


class ProbeRecord(BaseModel):
    """One memorization-probe result in ``probes.jsonl``."""

    model_config = _FROZEN

    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    recalled: bool
    direction: ProbeDirection
    parse_failed: bool
    model: str
    created_at: datetime


@dataclass(frozen=True)
class EvalPaths:
    """File layout under the repo-root ``eval/`` directory."""

    root: Path

    @property
    def events(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def fixtures(self) -> Path:
        return self.root / "fixtures"

    @property
    def headlines(self) -> Path:
        return self.root / "headlines"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def labels(self) -> Path:
        return self.results / "labels.jsonl"

    @property
    def baselines(self) -> Path:
        return self.results / "baselines.jsonl"

    @property
    def probes(self) -> Path:
        return self.results / "probes.jsonl"

    @property
    def registered_simulation(self) -> Path:
        """SimulationSettings defaults frozen at registration (committed, not a result)."""
        return self.root / "registered_simulation.json"

    def fixture(self, event_id: str, variant: Variant) -> Path:
        suffix = ".json" if variant == "named" else ".anon.json"
        return self.fixtures / f"{event_id}{suffix}"

    def headline_file(self, event_id: str) -> Path:
        return self.headlines / f"{event_id}.jsonl"


ModelT = TypeVar("ModelT", bound=BaseModel)


def read_jsonl(path: Path, model: type[ModelT]) -> list[ModelT]:
    """Parse one model per non-blank line; errors name the file, line and field."""
    records: list[ModelT] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(model.model_validate_json(line))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "line"
            raise ValueError(f"{path.name}:{number}: {where}: {first['msg']}") from exc
    return records


def read_jsonl_if_exists(path: Path, model: type[ModelT]) -> list[ModelT]:
    return read_jsonl(path, model) if path.exists() else []


def write_jsonl(path: Path, records: Sequence[BaseModel]) -> None:
    """Replace *path* atomically with one JSON object per record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, record: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")


def normalize_rumor(text: str) -> str:
    """Whitespace-insensitive key used to match stored ``Cycle.seed_rumor`` to an event."""
    return " ".join(text.split())


def sim_seed_for(seed: int) -> int:
    """Seed index 1, 2, 3 -> ``sim_seed`` 2101, 2102, 2103 (docs/DECISIONS.md#adr-eval-harness)."""
    if seed < 1:
        raise ValueError(f"seed index must be >= 1, got {seed}")
    return SEED_BASE + seed


def mean_bracket_temperature(brackets: Sequence[BracketConfig]) -> float:
    """Headcount-weighted mean bracket temperature, rounded to 2 dp (0.57 for v2)."""
    total = sum(b.count for b in brackets)
    if total == 0:
        raise ValueError("brackets contain no agents")
    return round(sum(b.count * b.temperature for b in brackets) / total, 2)


_SIGN: Final[dict[SignalType, int]] = {SignalType.BUY: 1, SignalType.HOLD: 0, SignalType.SELL: -1}


def headcount_score(decisions: Sequence[AgentDecision]) -> tuple[float, int]:
    """Mean signed confidence over valid votes, and the number of valid votes.

    Same formula as the headcount net-score formula (S = sum(s * c) / n,
    PARSE_ERROR excluded) for votes without a persona.
    """
    votes = [d for d in decisions if d.signal in _SIGN]
    if not votes:
        return 0.0, 0
    return sum(_SIGN[d.signal] * d.confidence for d in votes) / len(votes), len(votes)


def ablation_subset(event_ids: Sequence[str], k: int = ABLATION_SUBSET_SIZE) -> tuple[str, ...]:
    """The pre-registered ablation events: a seeded draw from the sorted ids."""
    pool = sorted(set(event_ids))
    if len(pool) <= k:
        return tuple(pool)
    return tuple(sorted(random.Random(BOOT_SEED).sample(pool, k)))


# --- Outcome labels (docs/DECISIONS.md#adr-eval-harness) -----------------------

NEW_YORK: Final = ZoneInfo("America/New_York")
SESSION_CLOSE: Final = time(16, 0)
K_FLAT: Final = 0.5
VOL_WINDOW: Final = 20
VOL_FLOOR: Final = 1e-4
HORIZON_DAYS: Final[dict[Horizon, int]] = {"1d": 1, "5d": 5}


class InsufficientHistoryError(ValueError):
    """Not enough sessions around an event to compute its label or fixture."""


@dataclass(frozen=True)
class PricePoint:
    """One daily bar: session date, close and (optionally) volume."""

    day: date
    close: float
    volume: int | None = None


def session_close_utc(day: date) -> datetime:
    """The 16:00 America/New_York close of *day* in UTC (DST-aware)."""
    return datetime.combine(day, SESSION_CLOSE, tzinfo=NEW_YORK).astimezone(UTC)


def base_index(days: Sequence[date], event_ts: datetime) -> int:
    """Index of the last session whose close is at or before *event_ts* (days ascending)."""
    index = -1
    for i, day in enumerate(days):
        if session_close_utc(day) > event_ts:
            break
        index = i
    if index < 0:
        raise InsufficientHistoryError("no session closed at or before the event")
    return index


def _direction(value: float, vol: float, sessions: int, k_flat: float) -> Direction:
    if abs(value) < k_flat * vol * math.sqrt(sessions):
        return "flat"
    return "up" if value > 0 else "down"


def compute_outcome(
    event_id: str,
    event_ts: datetime,
    ticker: Sequence[PricePoint],
    benchmark: Sequence[PricePoint],
    *,
    k_flat: float = K_FLAT,
    vol_window: int = VOL_WINDOW,
) -> OutcomeLabel:
    """Market-adjusted 1- and 5-day abnormal returns with a volatility-scaled flat zone."""
    t = {p.day: p.close for p in ticker if p.close > 0}
    b = {p.day: p.close for p in benchmark if p.close > 0}
    days = sorted(set(t) & set(b))
    i0 = base_index(days, event_ts)
    horizon = max(HORIZON_DAYS.values())
    if i0 < vol_window:
        raise InsufficientHistoryError(
            f"{event_id}: needs {vol_window} sessions before the event, has {i0}"
        )
    if i0 + horizon >= len(days):
        raise InsufficientHistoryError(
            f"{event_id}: needs {horizon} sessions after the event, has {len(days) - 1 - i0}"
        )

    def abnormal(start: int, end: int) -> float:
        ticker_ret = t[days[end]] / t[days[start]] - 1.0
        bench_ret = b[days[end]] / b[days[start]] - 1.0
        return ticker_ret - bench_ret

    daily = [abnormal(i - 1, i) for i in range(i0 - vol_window + 1, i0 + 1)]
    vol = max(stdev(daily), VOL_FLOOR)
    abn = {h: abnormal(i0, i0 + n) for h, n in HORIZON_DAYS.items()}
    return OutcomeLabel(
        event_id=event_id,
        abn_ret_1d=round(abn["1d"], 6),
        abn_ret_5d=round(abn["5d"], 6),
        vol_scale=round(vol, 6),
        label_1d=_direction(abn["1d"], vol, HORIZON_DAYS["1d"], k_flat),
        label_5d=_direction(abn["5d"], vol, HORIZON_DAYS["5d"], k_flat),
    )
