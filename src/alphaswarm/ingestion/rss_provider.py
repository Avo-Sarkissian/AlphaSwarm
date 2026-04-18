"""INGEST-02: Real RSSNewsProvider — httpx async fetch + feedparser parse.

D-01: RSS-only news provider — no API key, no rate limits.
D-02: Dual-source routing — ticker regex -> Yahoo Finance RSS; else Google News RSS.
D-03: Case-insensitive substring match for entity filter.
D-04: feedparser + httpx.
D-09: staleness='fresh' on success (including empty entries); 'fetch_failed' on exception.
D-10: no caching.
D-19: NEVER raises — every failure mode returns _fetch_failed_news_slice(entity, 'rss').

Pitfall 2 (HIGH): passing a URL directly to feedparser uses its sync
internal fetcher which trips bozo=True with URLError in this environment.
ALWAYS fetch bytes with httpx.AsyncClient first, then pass response.text
to feedparser.parse().

Pitfall 3 + 38-REVIEWS consensus #1 (HIGH): entry.published_parsed is
a time.struct_time that is UTC-intended per the RSS/Atom spec. Convert
to epoch seconds with calendar.timegm(published_parsed) — NEVER the
local-time-based stdlib converter, which would misinterpret the struct
as local time. On a machine in America/Los_Angeles that would shift
every published timestamp by 7-8 hours, causing max_age_hours filtering
to drop entries that are actually fresh (or keep entries that are
actually stale).

Pitfall 4: Yahoo Finance RSS returns HTTP 429 without an explicit User-Agent.
Always set User-Agent: Mozilla/5.0 AlphaSwarm/6.0 on every fetch.

38-REVIEWS consensus #2 (MEDIUM): httpx.AsyncClient MUST be constructed
with an explicit timeout. Without it, a slow upstream can hang a fetch
indefinitely *without raising* — the D-19 try/except would never trigger
and the simulation assembly (Phase 40) would block. Pass
timeout=_REQUEST_TIMEOUT_S to the constructor; keep per-request timeout=
as defense-in-depth.

T-38-01 (HIGH — URL injection): entity strings come from the seed rumor
(untrusted input). Mitigations:
  - Ticker path: regex ^[A-Z]{1,5}$ guarantees only ticker-safe chars reach
    the Yahoo URL; anything else routes through Google News where...
  - Google News path: urllib.parse.quote_plus(entity) percent-encodes every
    reserved character before string interpolation.
Both mitigations are asserted by unit tests.

International ticker routing (Gemini MEDIUM review — intentional scope):
The _TICKER_RE pattern ^[A-Z]{1,5}$ is tuned for US-listed symbols (AAPL,
MSFT, GOOG). International tickers with exchange suffixes — e.g.,
VOD.L (Vodafone on LSE), SHOP.TO (Shopify on TSX), 7203.T (Toyota on TSE)
— do NOT match this regex and therefore route to Google News RSS rather
than Yahoo Finance RSS. This is intentional per user decisions D-01/D-02
locked in CONTEXT.md: Google News has global publisher coverage and
reliably surfaces headlines for international symbols via full-text
search. If broader Yahoo-RSS international-ticker coverage becomes a
requirement in a later phase, the regex can be relaxed to
^[A-Z]{1,5}(\\.[A-Z]{1,2})?$ — but that is out of scope for Phase 38.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser  # type: ignore[import-untyped]
import httpx

from alphaswarm.ingestion.providers import _fetch_failed_news_slice
from alphaswarm.ingestion.types import NewsSlice

_SOURCE = "rss"
_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
_REQUEST_TIMEOUT_S = 10.0


def _route_url(entity: str) -> str:
    """Ticker -> Yahoo Finance RSS; everything else -> Google News RSS.

    T-38-01: Ticker regex is a whitelist; Google News path quotes the entity.
    """
    if _TICKER_RE.match(entity):
        return f"https://finance.yahoo.com/rss/headline?s={entity}"
    return (
        f"https://news.google.com/rss/search?q={quote_plus(entity)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


def _entry_age_hours(entry: dict[str, Any]) -> float | None:
    """Pitfall 3 + 38-REVIEWS consensus #1: published_parsed is UTC-intended.

    Use calendar.timegm (the UTC-aware converter), NOT the local-time
    stdlib converter which would interpret the struct as local time and
    skew max_age_hours filtering by the local timezone offset on non-UTC
    hosts.

    Returns None if the entry has no published_parsed — in that case the age
    filter is skipped (we treat undated entries as potentially fresh).
    """
    published_parsed = entry.get("published_parsed")
    if published_parsed is None:
        return None
    ts = calendar.timegm(published_parsed)  # UTC struct_time -> epoch seconds
    published_dt = datetime.fromtimestamp(ts, tz=UTC)
    return (datetime.now(UTC) - published_dt).total_seconds() / 3600.0


async def _fetch_one(
    client: httpx.AsyncClient, entity: str, max_age_hours: int
) -> NewsSlice:
    """Never-raise: any exception -> _fetch_failed_news_slice(entity, 'rss').

    Covered failure modes (any of which trips the outer except):
      - httpx.RequestError subclasses (timeout, DNS, connection refused)
      - httpx.TimeoutException (client-level or per-request timeout)
      - httpx.HTTPStatusError from r.raise_for_status() (429 without UA, 5xx)
      - feedparser bozo exceptions surfacing as attribute errors
      - calendar.timegm on malformed struct_time (ValueError/OverflowError)
      - ANY unexpected exception — D-19 contract
    """
    try:
        url = _route_url(entity)
        r = await client.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        feed = feedparser.parse(r.text)
        needle = entity.lower()
        headlines: list[str] = []
        for entry in feed.entries:
            title = entry.get("title", "")
            if not title or needle not in title.lower():
                continue
            age = _entry_age_hours(entry)
            if age is not None and age > max_age_hours:
                continue
            headlines.append(title)
        # Research Open Question 2: 0 entries from Yahoo with HTTP 200 is fresh,
        # not fetch_failed. We distinguish "nothing to report" from "could not fetch".
        return NewsSlice(
            entity=entity,
            headlines=tuple(headlines),
            fetched_at=datetime.now(UTC),
            source=_SOURCE,
            staleness="fresh",
        )
    except Exception:  # noqa: BLE001 — D-19 never-raise contract
        return _fetch_failed_news_slice(entity, _SOURCE)


class RSSNewsProvider:
    """Real NewsProvider backed by Yahoo Finance RSS + Google News RSS.

    A single httpx.AsyncClient is constructed per get_headlines call and
    shared across every entity fetch (via asyncio.gather) for connection
    reuse within the batch. Per D-10 no client is retained between calls.

    The client is constructed with an explicit timeout (Codex/Gemini review
    consensus #2) so that connection + read phases are both bounded — a
    hanging upstream cannot stall the provider even though the D-19
    contract only catches raised exceptions.
    """

    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]:
        if not entities:  # Pitfall 9 — empty input guard
            return {}
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT_S,  # 38-REVIEWS consensus #2: explicit timeout
        ) as client:
            slices = await asyncio.gather(
                *(_fetch_one(client, e, max_age_hours) for e in entities),
                return_exceptions=False,  # _fetch_one is contractually never-raise
            )
        # Duplicate entities collapse to single key (mirrors FakeNewsProvider semantics)
        return {s.entity: s for s in slices}
