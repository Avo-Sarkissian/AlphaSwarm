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

from typing import Literal, TypedDict

RegionExposure = Literal["US", "Asia", "global", "EM", "cash"]
Sensitivity = Literal["low", "med", "high"]


class SectorInfo(TypedDict):
    sector: str
    region_exposure: RegionExposure
    supply_chain_sensitivity: Sensitivity
    macro_beta: float  # [-1.0, 1.0]


SECTOR_MAP: dict[str, SectorInfo] = {
    "AAPL": {"sector": "consumer_tech", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.85},
    "AMZN": {"sector": "ecommerce_cloud", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.95},
    "ARM": {"sector": "semis_ip", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 1.0},
    "ASML": {"sector": "semis_litho", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 1.0},
    "AVGO": {"sector": "semis_networking", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.95},
    "BYDDY": {"sector": "auto_ev", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.8},
    "COHR": {"sector": "photonics", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.85},
    "CHAT": {"sector": "ai_etf", "region_exposure": "global", "supply_chain_sensitivity": "med", "macro_beta": 0.9},
    "CQQQ": {"sector": "china_tech_etf", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.85},
    "CRDO": {"sector": "semis_networking", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.95},
    "DBX": {"sector": "saas", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.6},
    "HIMS": {"sector": "consumer_health", "region_exposure": "US", "supply_chain_sensitivity": "med", "macro_beta": 0.55},
    "HON": {"sector": "industrials", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.7},
    "ISRG": {"sector": "medtech", "region_exposure": "global", "supply_chain_sensitivity": "med", "macro_beta": 0.75},
    "LPL": {"sector": "displays", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.6},
    "MRVL": {"sector": "semis_networking", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.95},
    "NIO": {"sector": "auto_ev", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 0.85},
    "NKE": {"sector": "consumer_apparel", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.6},
    "NVDA": {"sector": "semis_ai_accel", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 1.0},
    "PLTR": {"sector": "enterprise_ai", "region_exposure": "global", "supply_chain_sensitivity": "low", "macro_beta": 0.85},
    "PYPL": {"sector": "fintech", "region_exposure": "global", "supply_chain_sensitivity": "low", "macro_beta": 0.7},
    "QQQ": {"sector": "large_cap_tech_etf", "region_exposure": "US", "supply_chain_sensitivity": "med", "macro_beta": 0.9},
    "SCHW": {"sector": "brokerage", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.75},
    "SOFI": {"sector": "fintech", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.8},
    "SPY": {"sector": "broad_market_etf", "region_exposure": "US", "supply_chain_sensitivity": "med", "macro_beta": 1.0},
    "SWYXX": {"sector": "money_market", "region_exposure": "cash", "supply_chain_sensitivity": "low", "macro_beta": 0.0},
    "TLN": {"sector": "utilities_nuclear", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.4},
    "TSLA": {"sector": "auto_ev", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.9},
    "TSM": {"sector": "semis_foundry", "region_exposure": "Asia", "supply_chain_sensitivity": "high", "macro_beta": 1.0},
    "VRT": {"sector": "datacenter_infra", "region_exposure": "global", "supply_chain_sensitivity": "high", "macro_beta": 0.9},
    "VST": {"sector": "utilities_power", "region_exposure": "US", "supply_chain_sensitivity": "low", "macro_beta": 0.45},
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
    # when the seed explicitly named them. See SWEEP-260528 B-8.
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
