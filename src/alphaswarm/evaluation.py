"""Point-in-time evaluation: records, outcome labels and forecast scoring.

Pure functions plus small synchronous file helpers: no network, no Neo4j, no event
loop. The scripts under the repo-root ``eval/`` directory fetch prices, launch runs
and read cycles; every constant here is pre-registered before any evaluation run
(docs/DECISIONS.md#adr-eval-harness). Callers inside an event loop wrap the file
helpers in ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import NormalDist, fmean, stdev
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
    benchmark: str = Field(default="IVV", pattern=TICKER_PATTERN)  # an S&P 500 ETF
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

    The headcount net score S = sum(s * c) / n, with s = +1 for BUY, 0 for HOLD and -1
    for SELL and c the confidence: PARSE_ERROR is excluded and every valid vote counts
    once, with no persona or influence weight.
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
EARLY_CLOSE: Final = time(13, 0)
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


def points_from_rows(rows: Iterable[tuple[date, float, float | None]]) -> list[PricePoint]:
    """Daily bars from (day, close, volume) rows, ascending; NaN or non-positive closes skipped."""
    points: list[PricePoint] = []
    for day, close, volume in rows:
        value = float(close)
        if math.isnan(value) or value <= 0:
            continue
        shares = None if volume is None or math.isnan(float(volume)) else int(volume)
        points.append(PricePoint(day=day, close=value, volume=shares))
    return sorted(points, key=lambda p: p.day)


def is_early_close(day: date) -> bool:
    """The NYSE's regular 13:00 closes: the day after Thanksgiving, and July 3 and
    December 24 from Monday to Thursday (on a Friday each is the observed holiday)."""
    if (day.month, day.day) in ((7, 3), (12, 24)):
        return day.weekday() < 4
    if day.month != 11:
        return False
    first = date(day.year, 11, 1)
    thanksgiving = first + timedelta(days=(3 - first.weekday()) % 7 + 21)
    return day == thanksgiving + timedelta(days=1)


def session_close_utc(day: date) -> datetime:
    """The America/New_York close of *day* in UTC (DST-aware): 16:00, 13:00 on an early close."""
    close = EARLY_CLOSE if is_early_close(day) else SESSION_CLOSE
    return datetime.combine(day, close, tzinfo=NEW_YORK).astimezone(UTC)


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
        raise InsufficientHistoryError(f"{event_id}: needs {vol_window} sessions before the event, has {i0}")
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


# --- Scoring (docs/DECISIONS.md#adr-eval-harness) ------------------------------

CLIP_EPS: Final = 0.01
N_BOOT: Final = 2000
ALPHA: Final = 0.05
RELIABILITY_BINS: Final = 5


def p_up(score: float) -> float:
    """Probability of an up move implied by a score in [-1, 1]."""
    return min(1.0, max(0.0, (1.0 + score) / 2.0))


def brier(prob_up: float, up: bool) -> float:
    return (prob_up - (1.0 if up else 0.0)) ** 2


def log_loss(prob_up: float, up: bool, *, eps: float = CLIP_EPS) -> float:
    p = min(max(prob_up, eps), 1.0 - eps)
    return -math.log(p if up else 1.0 - p)


def wilson_interval(successes: int, n: int, *, alpha: float = ALPHA) -> tuple[float, float] | None:
    """Wilson score interval for a binomial rate; None when n is 0."""
    if n <= 0:
        return None
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks; ties share the average of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for k in range(start, end + 1):
            ranks[order[k]] = (start + end) / 2.0 + 1.0
        start = end + 1
    return ranks


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman correlation; None for fewer than 3 points or a constant series."""
    if len(xs) != len(ys):
        raise ValueError("spearman_rho needs equal-length sequences")
    if len(xs) < 3:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = fmean(rx), fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0.0 or syy == 0.0:
        return None
    return sxy / math.sqrt(sxx * syy)


@dataclass(frozen=True)
class ReliabilityBin:
    lo: float
    hi: float
    n: int
    mean_p: float | None
    freq: float | None


def reliability_bins(pairs: Sequence[tuple[float, bool]], *, n_bins: int = RELIABILITY_BINS) -> list[ReliabilityBin]:
    """Equal-width bins of forecast P(up) with the observed up frequency."""
    bins: list[ReliabilityBin] = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        last = b == n_bins - 1
        members = [(p, up) for p, up in pairs if lo <= p < hi or (last and p == 1.0)]
        if members:
            mean_p = fmean(p for p, _ in members)
            freq = sum(1 for _, up in members if up) / len(members)
            bins.append(ReliabilityBin(lo, hi, len(members), mean_p, freq))
        else:
            bins.append(ReliabilityBin(lo, hi, 0, None, None))
    return bins


@dataclass(frozen=True)
class Interval:
    """Mean of all units with a percentile bootstrap interval over clusters."""

    mean: float
    lo: float | None
    hi: float | None
    n_clusters: int
    n_units: int


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    position = q * (len(sorted_values) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    frac = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def cluster_bootstrap(
    clusters: Mapping[str, Sequence[float]],
    *,
    rng: random.Random,
    n_boot: int = N_BOOT,
    alpha: float = ALPHA,
) -> Interval | None:
    """Resample clusters (events) with replacement; None without data, no interval for one."""
    keys = sorted(k for k, values in clusters.items() if values)
    if not keys:
        return None
    units = [x for k in keys for x in clusters[k]]
    mean = fmean(units)
    if len(keys) < 2:
        return Interval(mean, None, None, len(keys), len(units))
    stats: list[float] = []
    for _ in range(n_boot):
        sample = [x for _ in keys for x in clusters[rng.choice(keys)]]
        stats.append(fmean(sample))
    stats.sort()
    return Interval(
        mean,
        _quantile(stats, alpha / 2.0),
        _quantile(stats, 1.0 - alpha / 2.0),
        len(keys),
        len(units),
    )


def boot_rng(purpose: str) -> random.Random:
    """Seeded per table cell, so the same data always yields the same interval."""
    digest = hashlib.blake2b(f"{BOOT_SEED}:{purpose}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


def lean3(score: float, deadband: float) -> Direction:
    """Net-score lean as a direction: up above the deadband, down below its negative."""
    if score > deadband:
        return "up"
    if score < -deadband:
        return "down"
    return "flat"


@dataclass(frozen=True)
class ForecasterResult:
    forecaster: str
    horizon: Horizon
    n_events: int
    n_directional: int
    hits: int
    hit_rate: float | None
    hit_ci: tuple[float, float] | None
    brier: float | None
    log_loss: float | None
    spearman: float | None
    accuracy3: float | None


def mean_by_event(rows: Iterable[tuple[str, float]]) -> dict[str, float]:
    """Average the per-seed scores of each event."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for event_id, score in rows:
        grouped[event_id].append(score)
    return {event_id: fmean(values) for event_id, values in grouped.items()}


def score_forecaster(
    name: str,
    scores: Mapping[str, float],
    labels: Mapping[str, OutcomeLabel],
    horizon: Horizon,
    *,
    deadband: float,
) -> ForecasterResult:
    """Hit rate, Brier, log loss, Spearman and 3-class accuracy over labelled events."""
    events = sorted(e for e in scores if e in labels)
    directional = [e for e in events if labels[e].label(horizon) != "flat"]
    hits = 0
    briers: list[float] = []
    losses: list[float] = []
    for e in directional:
        up = labels[e].label(horizon) == "up"
        s = scores[e]
        if (s > 0 and up) or (s < 0 and not up):
            hits += 1
        briers.append(brier(p_up(s), up))
        losses.append(log_loss(p_up(s), up))
    rho = spearman_rho([scores[e] for e in events], [labels[e].abn_ret(horizon) for e in events]) if events else None
    accuracy3 = (
        fmean(1.0 if lean3(scores[e], deadband) == labels[e].label(horizon) else 0.0 for e in events)
        if events
        else None
    )
    return ForecasterResult(
        forecaster=name,
        horizon=horizon,
        n_events=len(events),
        n_directional=len(directional),
        hits=hits,
        hit_rate=hits / len(directional) if directional else None,
        hit_ci=wilson_interval(hits, len(directional)),
        brier=fmean(briers) if briers else None,
        log_loss=fmean(losses) if losses else None,
        spearman=rho,
        accuracy3=accuracy3,
    )


def brier_by_event(
    scores: Mapping[str, float], labels: Mapping[str, OutcomeLabel], horizon: Horizon
) -> dict[str, float]:
    """Per-event Brier score on directional events only."""
    return {
        e: brier(p_up(s), labels[e].label(horizon) == "up")
        for e, s in scores.items()
        if e in labels and labels[e].label(horizon) != "flat"
    }


def paired_difference(a: Mapping[str, float], b: Mapping[str, float], *, rng: random.Random) -> Interval | None:
    """Mean of a - b over the events both cover, bootstrapped over events."""
    common = sorted(set(a) & set(b))
    return cluster_bootstrap({e: [a[e] - b[e]] for e in common}, rng=rng)


def fmt(value: float | None, spec: str = ".3f") -> str:
    return "n/a" if value is None else format(value, spec)


def fmt_interval(interval: Interval | None, spec: str = "+.3f") -> str:
    if interval is None:
        return "n/a"
    if interval.lo is None or interval.hi is None:
        return f"{interval.mean:{spec}} [n/a]"
    return f"{interval.mean:{spec}} [{interval.lo:{spec}}, {interval.hi:{spec}}]"


def fmt_rate(rate: float | None, ci: tuple[float, float] | None) -> str:
    if rate is None or ci is None:
        return "n/a"
    return f"{rate:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]"


def verdict(interval: Interval | None) -> str:
    """Pre-registered claim rule for a difference swarm - other.

    See docs/DECISIONS.md#adr-eval-harness.
    """
    if interval is None or interval.lo is None or interval.hi is None:
        return "insufficient data"
    if interval.hi < 0:
        return "swarm better"
    if interval.lo > 0:
        return "swarm worse"
    return "inconclusive"


def markdown_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"
