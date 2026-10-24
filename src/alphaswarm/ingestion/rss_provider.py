"""RSSNewsProvider: headlines from Yahoo Finance RSS (tickers) and Google News RSS.

Invariants:
- Never raises: any failure for an entity becomes a ``fetch_failed`` NewsSlice
  (docs/DECISIONS.md#adr-provider-never-raise).
- Routing: an entity with a swarm-resolved ticker matching ``TICKER_PATTERN`` uses
  the Yahoo Finance per-ticker feed; every other entity, acronyms such as FED
  included, goes to Google News with the entity URL-encoded
  (docs/DECISIONS.md#p38-d-02).
- Bytes are fetched with ``httpx.AsyncClient`` (explicit timeout; a User-Agent,
  without which Yahoo answers 429) and parsed with ``feedparser`` in a worker
  thread; feedparser never fetches URLs itself. No cache.
- Google entries are kept when the raw title contains the entity as a whole word,
  case-insensitively; Yahoo per-ticker entries are not filtered
  (docs/DECISIONS.md#p38-d-03).
- ``published_parsed`` is UTC and is converted with ``calendar.timegm``.
- Every title passes ``sanitize_headline`` before it can reach an agent prompt;
  titles that sanitise to nothing are dropped (docs/DECISIONS.md#adr-security-2026-08).
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser  # type: ignore[import-untyped]
import httpx

from alphaswarm.ingestion.providers import _fetch_failed_news_slice
from alphaswarm.ingestion.types import NewsSlice
from alphaswarm.security.sanitize import sanitize_headline
from alphaswarm.types import TICKER_PATTERN

_SOURCE = "rss"
_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"
# T-38-01: only a symbol matching TICKER_PATTERN may reach the Yahoo URL.
_TICKER_RE = re.compile(TICKER_PATTERN)
_REQUEST_TIMEOUT_S = 10.0


def _route_url(entity: str, ticker: str | None) -> str:
    """Resolved ticker -> Yahoo per-ticker RSS; everything else -> Google News RSS.

    Only swarm-resolved symbols reach Yahoo (docs/DECISIONS.md#adr-ticker-resolution),
    so acronyms such as FED never do. T-38-01: the ticker is whitelisted by
    TICKER_PATTERN and the Google path quotes the entity.
    """
    if ticker is not None and _TICKER_RE.match(ticker):
        return f"https://finance.yahoo.com/rss/headline?s={ticker}"
    return f"https://news.google.com/rss/search?q={quote_plus(entity)}&hl=en-US&gl=US&ceid=US:en"


def _entity_pattern(entity: str) -> re.Pattern[str]:
    """Case-insensitive whole-word match of the entity name (docs/DECISIONS.md#p38-d-03)."""
    return re.compile(rf"(?<!\w){re.escape(entity.strip())}(?!\w)", re.IGNORECASE)


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


async def _fetch_one(client: httpx.AsyncClient, entity: str, max_age_hours: int, ticker: str | None) -> NewsSlice:
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
        url = _route_url(entity, ticker)
        r = await client.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        # feedparser is CPU-bound and synchronous: parse in a worker thread so the
        # event loop keeps serving the 5 Hz broadcaster (docs/DECISIONS.md#p38-d-04).
        feed = await asyncio.to_thread(feedparser.parse, r.content)
        # A per-ticker Yahoo feed is already about the symbol and its titles rarely
        # repeat it, so it is not filtered; Google search results are
        # (docs/DECISIONS.md#p38-d-03).
        pattern = None if url.startswith("https://finance.yahoo.com/") else _entity_pattern(entity)
        headlines: list[str] = []
        for entry in feed.entries:
            title = entry.get("title", "")
            if not title or (pattern is not None and not pattern.search(title)):
                continue
            age = _entry_age_hours(entry)
            if age is not None and age > max_age_hours:
                continue
            # F3: the entity filter above matches on the RAW title (unchanged
            # matching semantics); only the stored text is sanitized. A title
            # that sanitizes to nothing carried no readable content.
            clean_title = sanitize_headline(title)
            if not clean_title:
                continue
            headlines.append(clean_title)
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

    ITEM 5 of quick task 260512-jqn: optional audit sink mirrors the
    yfinance_provider pattern. attach_audit_sink() is lifecycle-injected
    from alphaswarm.web.app after app_state is constructed.
    """

    def __init__(self) -> None:
        self._audit_sink: object | None = None

    def attach_audit_sink(self, state_store: object) -> None:
        """Attach a StateStore-shaped object (`record_data_source` callable)."""
        self._audit_sink = state_store

    def _audit(self, query: str, result: str, used: bool) -> None:
        """Non-fatal audit shim — never raises into the fetch path."""
        sink = self._audit_sink
        if sink is None:
            return
        with contextlib.suppress(Exception):  # observability must never break the fetch
            sink.record_data_source(  # type: ignore[attr-defined]
                source="rss",
                query=query,
                result=result,
                used=used,
            )

    async def get_headlines(
        self,
        entities: list[str],
        *,
        max_age_hours: int = 72,
        tickers: Mapping[str, str] | None = None,
    ) -> dict[str, NewsSlice]:
        if not entities:  # Pitfall 9 — empty input guard
            return {}
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT_S,  # 38-REVIEWS consensus #2: explicit timeout
        ) as client:
            slices = await asyncio.gather(
                *(_fetch_one(client, e, max_age_hours, (tickers or {}).get(e)) for e in entities),
                return_exceptions=False,  # _fetch_one is contractually never-raise
            )
        for s in slices:
            ok = s.staleness != "fetch_failed"
            self._audit(
                query=f"headlines:{s.entity}",
                result="ok" if ok else "error: fetch_failed",
                used=True,
            )
        # Duplicate entities collapse to single key (mirrors FakeNewsProvider semantics)
        return {s.entity: s for s in slices}
