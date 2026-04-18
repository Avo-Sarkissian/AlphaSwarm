"""INGEST-02: Real RSSNewsProvider — httpx async fetch + feedparser parse.

D-01: RSS-only news provider — no API key, no rate limits.
D-02: Dual-source routing — ticker regex -> Yahoo Finance RSS; else Google News RSS.
D-03: Case-insensitive substring match for entity filter.
D-04: feedparser + httpx.
D-09: staleness='fresh' on success (including empty entries); 'fetch_failed' on exception.
D-10: no caching.
D-19: NEVER raises — every failure mode returns _fetch_failed_news_slice(entity, 'rss').

Pitfall 2 (HIGH): feedparser.parse(url) uses a sync URL fetcher that trips
bozo=True with URLError in this environment. ALWAYS fetch bytes with
httpx.AsyncClient first, then pass response.text to feedparser.parse().

Pitfall 3 (as corrected by 38-REVIEWS consensus #1): entry.published_parsed
is time.struct_time, UTC-intended per RSS/Atom spec. Convert with
calendar.timegm(published_parsed) — NOT time.mktime(...) which would
misinterpret the struct as local time and introduce timezone skew into
max_age_hours filtering.

Pitfall 4: Yahoo Finance RSS returns HTTP 429 without an explicit User-Agent.
Always set User-Agent: Mozilla/5.0 AlphaSwarm/6.0 on every fetch.

T-38-01 (HIGH): URL injection via entity string. Ticker path enforces
^[A-Z]{1,5}$ regex; Google News path wraps entity in urllib.parse.quote_plus.
"""

from __future__ import annotations

from alphaswarm.ingestion.types import NewsSlice


class RSSNewsProvider:
    """Real NewsProvider backed by Yahoo Finance RSS + Google News RSS. Task 2 implements."""

    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]:
        raise NotImplementedError("RSSNewsProvider.get_headlines — Task 2")
