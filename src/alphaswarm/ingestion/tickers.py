"""Swarm-side ticker resolution for seed entities (docs/DECISIONS.md#adr-ticker-resolution).

The orchestrator proposes a ticker per company entity; this module decides which
proposals the swarm may use. With the SEC company map cached locally a symbol is
kept only when the SEC title agrees with the entity name, and names resolve
through the map. Without the map, symbols are trusted unless they are known
non-company acronyms. Never imports alphaswarm.advisory: the advisory sector map
is derived from the owner's portfolio and must not shape what agents see.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

import structlog

from alphaswarm.types import TICKER_PATTERN, EntityType, SeedEntity, SeedEvent

log = structlog.get_logger(component="ingestion")

TICKER_RE: Final = re.compile(TICKER_PATTERN)

# Institutions, macro series and generic finance acronyms that look like tickers.
NON_TICKER_ACRONYMS: Final[frozenset[str]] = frozenset(
    {
        "BOE",
        "BOJ",
        "CEO",
        "CFO",
        "CPI",
        "DOJ",
        "ECB",
        "ESG",
        "ETF",
        "EU",
        "FDA",
        "FED",
        "FOMC",
        "FTC",
        "GDP",
        "IMF",
        "IPO",
        "LBO",
        "NATO",
        "NYSE",
        "OECD",
        "OPEC",
        "PBOC",
        "PCE",
        "PPI",
        "SEC",
        "SPAC",
        "UK",
        "US",
        "USA",
        "WTO",
    }
)

# Brand names whose SEC title differs; generic, not derived from any portfolio.
BUILTIN_ALIASES: Final[Mapping[str, str]] = MappingProxyType({"google": "GOOGL", "facebook": "META"})

_SUFFIXES: Final = frozenset(
    {
        "a",
        "ag",
        "b",
        "c",
        "class",
        "co",
        "common",
        "company",
        "corp",
        "corporation",
        "group",
        "holding",
        "holdings",
        "inc",
        "incorporated",
        "limited",
        "ltd",
        "nv",
        "ordinary",
        "plc",
        "sa",
        "se",
        "shares",
        "stock",
        "the",
    }
)
_NON_ALNUM_RE: Final = re.compile(r"[^a-z0-9 ]+")
# Leading words too common to prove that two company names agree on their own.
_GENERIC_FIRST_WORDS: Final = frozenset(
    {
        "american",
        "bank",
        "china",
        "first",
        "general",
        "global",
        "great",
        "international",
        "national",
        "new",
        "royal",
        "united",
    }
)


def normalize_company_name(name: str) -> str:
    """Lower-case, '&' -> 'and', punctuation dropped, corporate suffixes and a leading 'the' removed."""
    text = _NON_ALNUM_RE.sub(" ", name.lower().replace("&", " and "))
    tokens = text.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    return " ".join(tokens)


def _names_agree(entity_name: str, title: str | None) -> bool:
    """Normalized names agree: equal, one a word-prefix of the other, or the same
    distinctive first word (a generic first word such as "first" never counts)."""
    if not entity_name or not title:
        return False
    first = entity_name.split()[0]
    return (
        entity_name == title
        or title.startswith(entity_name + " ")
        or entity_name.startswith(title + " ")
        or (first == title.split()[0] and first not in _GENERIC_FIRST_WORDS)
    )


@dataclass(frozen=True)
class TickerResolver:
    """Ticker -> normalized SEC title, and normalized title -> ticker."""

    tickers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    by_name: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    source: Literal["sec", "none"] = "none"

    @classmethod
    def empty(cls) -> TickerResolver:
        return cls()

    @classmethod
    def from_sec_payload(cls, payload: object) -> TickerResolver:
        """Build from https://www.sec.gov/files/company_tickers.json ({"0": {"ticker", "title"}, ...})."""
        if not isinstance(payload, Mapping):
            raise ValueError("the SEC ticker map must be a JSON object")
        tickers: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for entry in payload.values():
            if not isinstance(entry, Mapping):
                continue
            ticker = str(entry.get("ticker", "")).strip().upper()
            title = normalize_company_name(str(entry.get("title", "")))
            if not TICKER_RE.match(ticker) or not title:
                continue
            tickers.setdefault(ticker, title)
            by_name.setdefault(title, ticker)
        if not tickers:
            raise ValueError("the SEC ticker map has no usable entries")
        return cls(MappingProxyType(tickers), MappingProxyType(by_name), "sec")

    def resolve(self, entity: SeedEntity) -> str | None:
        """The ticker the swarm may use for *entity*, or None."""
        if entity.type is not EntityType.COMPANY:
            return None
        name = normalize_company_name(entity.name)
        candidate = entity.ticker
        if self.source == "sec":
            if candidate is not None and _names_agree(name, self.tickers.get(candidate)):
                return candidate
            by_name = self.by_name.get(name)
            if by_name is not None:
                return by_name
            alias = BUILTIN_ALIASES.get(name)
            return alias if alias is not None and alias in self.tickers else None
        alias = BUILTIN_ALIASES.get(name)
        if alias is not None:
            return alias
        if candidate is not None and candidate not in NON_TICKER_ACRONYMS:
            return candidate
        return None

    def resolve_seed_event(self, event: SeedEvent) -> SeedEvent:
        """Copy of *event* whose entity tickers are the resolved ones (None when unresolved)."""
        entities = [e.model_copy(update={"ticker": self.resolve(e)}) for e in event.entities]
        return event.model_copy(update={"entities": entities})


def _read_resolver(path: Path) -> TickerResolver:
    if not path.is_file():
        return TickerResolver.empty()
    return TickerResolver.from_sec_payload(json.loads(path.read_text(encoding="utf-8")))


async def load_ticker_resolver(path: Path) -> TickerResolver:
    """Load the cached SEC map; a missing or invalid file yields the empty resolver."""
    try:
        resolver = await asyncio.to_thread(_read_resolver, path)
    except (OSError, ValueError) as exc:
        log.warning("ticker_map_invalid", error_type=type(exc).__name__)
        return TickerResolver.empty()
    log.info("ticker_map_loaded", source=resolver.source, tickers=len(resolver.tickers))
    return resolver
