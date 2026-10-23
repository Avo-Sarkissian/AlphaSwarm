"""Curated ticker → sector enrichment map (ITEM 6 of quick task 260512-jqn).

Covers the user's 32 unique Schwab + Roth holdings — duplicates of MRVL
and QQQ (Roth vs taxable) resolve to the same entry. Unknown tickers
fall back to a global-neutral default.

Used by alphaswarm.advisory.engine before prompt synthesis to:
  • inform per-holding relevance scoring (entity_impact * macro_beta)
  • narrow the top-15 holdings sent with full enrichment vs the
    rest with sector tag only

Macro-beta is the holding's sensitivity to broad market moves:
  +1.0 = full leverage, 0.0 = cash-like, negative not used here.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, TypedDict

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphaswarm.config import PROJECT_ROOT

RegionExposure = Literal["US", "Asia", "global", "EM", "cash"]
Sensitivity = Literal["low", "med", "high"]


class SectorInfo(TypedDict):
    sector: str
    region_exposure: RegionExposure
    supply_chain_sensitivity: Sensitivity
    macro_beta: float  # [-1.0, 1.0]


SECTOR_MAP: dict[str, SectorInfo] = {
    "AAPL": {
        "sector": "consumer_tech",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.85,
    },
    "AMZN": {
        "sector": "ecommerce_cloud",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.95,
    },
    "ARM": {"sector": "semis_ip", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 1.0},
    "ASML": {
        "sector": "semis_litho",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 1.0,
    },
    "AVGO": {
        "sector": "semis_networking",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.95,
    },
    "BYDDY": {"sector": "auto_ev", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.8},
    "COHR": {
        "sector": "photonics",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.85,
    },
    "CHAT": {"sector": "ai_etf", "region_exposure": "global", "supply_chain_sensitivity": "med", "macro_beta": 0.9},
    "CQQQ": {
        "sector": "china_tech_etf",
        "region_exposure": "Asia",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.85,
    },
    "CRDO": {
        "sector": "semis_networking",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.95,
    },
    "DBX": {"sector": "saas", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.6},
    "HIMS": {
        "sector": "consumer_health",
        "region_exposure": "US",
        "supply_chain_sensitivity": "med",
        "macro_beta": 0.55,
    },
    "HON": {
        "sector": "industrials",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.7,
    },
    "ISRG": {"sector": "medtech", "region_exposure": "global", "supply_chain_sensitivity": "med", "macro_beta": 0.75},
    "LPL": {"sector": "displays", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.6},
    "MRVL": {
        "sector": "semis_networking",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.95,
    },
    "NIO": {"sector": "auto_ev", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.85},
    "NKE": {
        "sector": "consumer_apparel",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.6,
    },
    "NVDA": {
        "sector": "semis_ai_accel",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 1.0,
    },
    "PLTR": {
        "sector": "enterprise_ai",
        "region_exposure": "global",
        "supply_chain_sensitivity": "low",
        "macro_beta": 0.85,
    },
    "PYPL": {"sector": "fintech", "region_exposure": "global", "supply_chain_sensitivity": "low", "macro_beta": 0.7},
    "QQQ": {
        "sector": "large_cap_tech_etf",
        "region_exposure": "US",
        "supply_chain_sensitivity": "med",
        "macro_beta": 0.9,
    },
    "SCHW": {"sector": "brokerage", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.75},
    "SOFI": {"sector": "fintech", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.8},
    "SPY": {
        "sector": "broad_market_etf",
        "region_exposure": "US",
        "supply_chain_sensitivity": "med",
        "macro_beta": 1.0,
    },
    "SWYXX": {
        "sector": "money_market",
        "region_exposure": "cash",
        "supply_chain_sensitivity": "low",
        "macro_beta": 0.0,
    },
    "TLN": {
        "sector": "utilities_nuclear",
        "region_exposure": "US",
        "supply_chain_sensitivity": "low",
        "macro_beta": 0.4,
    },
    "TSLA": {"sector": "auto_ev", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.9},
    "TSM": {
        "sector": "semis_foundry",
        "region_exposure": "Asia",
        "supply_chain_sensitivity": "high",
        "macro_beta": 1.0,
    },
    "VRT": {
        "sector": "datacenter_infra",
        "region_exposure": "global",
        "supply_chain_sensitivity": "high",
        "macro_beta": 0.9,
    },
    "VST": {
        "sector": "utilities_power",
        "region_exposure": "US",
        "supply_chain_sensitivity": "low",
        "macro_beta": 0.45,
    },
    "WTAI": {"sector": "ai_etf", "region_exposure": "global", "supply_chain_sensitivity": "med", "macro_beta": 0.9},
}


UNKNOWN_SECTOR: SectorInfo = {
    "sector": "unknown",
    "region_exposure": "global",
    "supply_chain_sensitivity": "med",
    # macro_beta=0.5 so unknown tickers still get a meaningful relevance score
    # when the seed matches. With 0.0 (previous value) the relevance formula
    # `|impact| × |beta| + 0.5 × seed_match` would zero out the entity-impact
    # contribution and unknown tickers would always rank at the bottom even
    # when the seed explicitly named them. See docs/DECISIONS.md#sweep-b-8.
    "macro_beta": 0.5,
}


def lookup(ticker: str) -> SectorInfo:
    """Return SectorInfo for `ticker` (case-insensitive), or UNKNOWN default."""
    return SECTOR_MAP.get(ticker.upper(), UNKNOWN_SECTOR)


# Company/common name → ticker, for resolving free-form Entity names emitted by
# the seed orchestrator (e.g. "NVIDIA", "Taiwan Semiconductor") back to the
# ticker symbols the advisory keys on (F-07). Portfolio-scoped, mirroring
# SECTOR_MAP's curation discipline; extend alongside SECTOR_MAP when holdings
# change. Keys are lowercased. Pure ETFs / money-market funds are intentionally
# omitted — rumors name companies, not the user's fund tickers — but they still
# resolve via the ticker pass-through in resolve_ticker().
COMPANY_ALIASES: dict[str, str] = {
    "apple": "AAPL",
    "amazon": "AMZN",
    "arm": "ARM",
    "arm holdings": "ARM",
    "asml": "ASML",
    "broadcom": "AVGO",
    "byd": "BYDDY",
    "coherent": "COHR",
    "credo": "CRDO",
    "credo technology": "CRDO",
    "dropbox": "DBX",
    "hims": "HIMS",
    "hims & hers": "HIMS",
    "hims and hers": "HIMS",
    "honeywell": "HON",
    "intuitive surgical": "ISRG",
    "lg display": "LPL",
    "marvell": "MRVL",
    "marvell technology": "MRVL",
    "nio": "NIO",
    "nike": "NKE",
    "nvidia": "NVDA",
    "palantir": "PLTR",
    "paypal": "PYPL",
    "schwab": "SCHW",
    "charles schwab": "SCHW",
    "sofi": "SOFI",
    "sofi technologies": "SOFI",
    "talen": "TLN",
    "talen energy": "TLN",
    "tesla": "TSLA",
    "tsmc": "TSM",
    "taiwan semiconductor": "TSM",
    "vertiv": "VRT",
    "vistra": "VST",
}


def resolve_ticker(entity_name: str) -> str | None:
    """Resolve a free-form Entity name to a portfolio ticker, or None.

    Resolution order:
      1. Pass-through: the name is already a known ticker (e.g. "NVDA", "tsm").
      2. Alias: a curated company/common name (e.g. "NVIDIA", "Taiwan Semiconductor").

    Returns None when the name maps to no held position, so the caller can skip
    it rather than score an unrelated holding.
    """
    name = entity_name.strip()
    if not name:
        return None
    if name.upper() in SECTOR_MAP:
        return name.upper()
    return COMPANY_ALIASES.get(name.lower())


# ---------------------------------------------------------------------------
# Data-driven map: the curated owner data moves to a local, gitignored file
# (docs/DECISIONS.md#adr-holdings-isolation).
# ---------------------------------------------------------------------------

log = structlog.get_logger(component="advisory.sector_map")

SECTOR_MAP_EXAMPLE_PATH: Final[Path] = PROJECT_ROOT / "examples" / "sector_map.example.json"
_TICKER_KEY_RE: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_SETUP_HINT: Final = (
    "copy examples/sector_map.example.json to data/sector_map.local.json and replace the entries with your holdings"
)
_INVALID_HINT: Final = (
    "the local sector map failed validation; compare data/sector_map.local.json with examples/sector_map.example.json"
)
SectorMapSource = Literal["local", "example", "none"]


class _SectorEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sector: str = Field(min_length=1, max_length=64)
    region_exposure: RegionExposure
    supply_chain_sensitivity: Sensitivity
    macro_beta: float = Field(ge=-1.0, le=1.0)


class _SectorMapFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = ""
    tickers: dict[str, _SectorEntry]
    aliases: dict[str, str] = Field(default_factory=dict)

    @field_validator("tickers")
    @classmethod
    def _upper_ticker_keys(cls, value: dict[str, _SectorEntry]) -> dict[str, _SectorEntry]:
        normalized = {key.strip().upper(): entry for key, entry in value.items()}
        if not all(_TICKER_KEY_RE.fullmatch(key) for key in normalized):
            raise ValueError("every ticker key must look like a ticker symbol")
        return normalized

    @field_validator("aliases")
    @classmethod
    def _normalize_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        return {name.strip().lower(): ticker.strip().upper() for name, ticker in value.items() if name.strip()}

    @model_validator(mode="after")
    def _aliases_point_at_tickers(self) -> _SectorMapFile:
        if any(ticker not in self.tickers for ticker in self.aliases.values()):
            raise ValueError("every alias must point at a ticker in the same file")
        return self


@dataclass(frozen=True)
class SectorMap:
    """Ticker → SectorInfo plus company-name aliases, loaded from JSON.

    Build it with load_sector_map() or parse_sector_map(); EMPTY_SECTOR_MAP maps
    every ticker to UNKNOWN_SECTOR.
    """

    entries: Mapping[str, SectorInfo] = field(default_factory=lambda: MappingProxyType({}))
    aliases: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    source: SectorMapSource = "none"

    def lookup(self, ticker: str) -> SectorInfo:
        """SectorInfo for *ticker* (case-insensitive), or UNKNOWN_SECTOR."""
        return self.entries.get(ticker.strip().upper(), UNKNOWN_SECTOR)

    def resolve_ticker(self, entity_name: str, held: Collection[str]) -> str | None:
        """Resolve a free-form Entity name to one of the *held* tickers, or None.

        1. Pass-through: the name is itself a held ticker ("ZZZT", "zzzt").
        2. Alias: a curated company name that maps to a held ticker.
        Nothing resolves to a ticker the portfolio does not hold, so an unrelated
        entity can never score a holding.
        """
        name = entity_name.strip()
        if not name:
            return None
        held_upper = {ticker.upper() for ticker in held}
        if name.upper() in held_upper:
            return name.upper()
        target = self.aliases.get(name.lower())
        return target if target is not None and target in held_upper else None


EMPTY_SECTOR_MAP: Final[SectorMap] = SectorMap()


def parse_sector_map(raw: str, *, source: SectorMapSource) -> SectorMap:
    """Validate sector-map JSON; raises ValueError (pydantic ValidationError) when invalid."""
    parsed = _SectorMapFile.model_validate_json(raw)
    entries: dict[str, SectorInfo] = {
        ticker: SectorInfo(
            sector=entry.sector,
            region_exposure=entry.region_exposure,
            supply_chain_sensitivity=entry.supply_chain_sensitivity,
            macro_beta=entry.macro_beta,
        )
        for ticker, entry in parsed.tickers.items()
    }
    return SectorMap(
        entries=MappingProxyType(entries),
        aliases=MappingProxyType(dict(parsed.aliases)),
        source=source,
    )


def load_sector_map(path: Path, *, example: Path | None = SECTOR_MAP_EXAMPLE_PATH) -> SectorMap:
    """Load the owner's map from *path*; fall back to *example* when *path* is missing.

    A file that exists but is invalid yields EMPTY_SECTOR_MAP, never the example:
    a typo must not silently swap the owner's sectors for fictional ones. The
    advisory never fails because of the map. Logs carry the source, counts and,
    on a fallback, a fixed setup hint; never tickers or file contents
    (docs/DECISIONS.md#adr-holdings-isolation). Synchronous: async callers use
    asyncio.to_thread.
    """
    candidates: list[tuple[Path, SectorMapSource]] = [(path, "local")]
    if example is not None:
        candidates.append((example, "example"))
    for candidate, source in candidates:
        if not candidate.is_file():
            continue
        try:
            sector_map = parse_sector_map(candidate.read_text(encoding="utf-8"), source=source)
        except (OSError, ValueError) as exc:
            log.warning(
                "sector_map_invalid",
                source=source,
                error_type=exc.__class__.__name__,
                hint=_INVALID_HINT if source == "local" else _SETUP_HINT,
            )
            return EMPTY_SECTOR_MAP
        counts = {"entries": len(sector_map.entries), "aliases": len(sector_map.aliases)}
        if source == "local":
            log.info("sector_map_loaded", source=source, **counts)
        else:
            log.info("sector_map_loaded", source=source, **counts, hint=_SETUP_HINT)
        return sector_map
    log.info("sector_map_loaded", source="none", entries=0, aliases=0, hint=_SETUP_HINT)
    return EMPTY_SECTOR_MAP
