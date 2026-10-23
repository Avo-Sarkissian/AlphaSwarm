"""Ticker → sector enrichment for the advisory, loaded from a local JSON file.

The curated map describes the owner's own holdings, so it lives outside the
repository in data/sector_map.local.json (gitignored, settings.sector_map_path);
the repository ships only the fictional examples/sector_map.example.json
(docs/DECISIONS.md#adr-holdings-isolation). Unknown tickers fall back to
UNKNOWN_SECTOR, whose macro_beta of 0.5 keeps seed matches meaningful
(docs/DECISIONS.md#sweep-b-8).

Used by alphaswarm.advisory.engine to score per-holding relevance
(|entity_impact| x |macro_beta| + 0.5 x seed_match) and to resolve entity names
to held tickers. Macro-beta is the holding's sensitivity to broad market moves:
+1.0 = full leverage, 0.0 = cash-like.

File format::

    {"description": "...",
     "tickers": {"ZZZT": {"sector": "Industrial Automation", "region_exposure": "US",
                          "supply_chain_sensitivity": "high", "macro_beta": 0.9}},
     "aliases": {"zzzt holdings": "ZZZT"}}

Ticker keys are upper-cased and alias keys lower-cased on load; every alias must
point at a ticker in the same file. Load failures never block the advisory, and
logs carry counts only, never tickers.
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

from alphaswarm.settings import PROJECT_ROOT

log = structlog.get_logger(component="advisory.sector_map")

RegionExposure = Literal["US", "Asia", "global", "EM", "cash"]
Sensitivity = Literal["low", "med", "high"]
SectorMapSource = Literal["local", "example", "none"]

SECTOR_MAP_EXAMPLE_PATH: Final[Path] = PROJECT_ROOT / "examples" / "sector_map.example.json"
_TICKER_KEY_RE: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_SETUP_HINT: Final = (
    "copy examples/sector_map.example.json to data/sector_map.local.json and replace the entries with your holdings"
)
_INVALID_HINT: Final = (
    "the local sector map failed validation; compare data/sector_map.local.json with examples/sector_map.example.json"
)


class SectorInfo(TypedDict):
    sector: str
    region_exposure: RegionExposure
    supply_chain_sensitivity: Sensitivity
    macro_beta: float  # [-1.0, 1.0]


UNKNOWN_SECTOR: SectorInfo = {
    "sector": "unknown",
    "region_exposure": "global",
    "supply_chain_sensitivity": "med",
    # macro_beta=0.5 so unknown tickers still get a meaningful relevance score
    # when the seed names them; with 0.0 the entity-impact term would vanish and
    # unknown tickers would always rank last (docs/DECISIONS.md#sweep-b-8).
    "macro_beta": 0.5,
}


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
