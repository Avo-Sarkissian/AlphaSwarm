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
