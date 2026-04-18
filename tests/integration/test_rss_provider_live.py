"""INGEST-02 integration tests — real network.

These tests are auto-marked (enable_socket) by
tests/integration/conftest.py — without that marker the global
`--disable-socket` gate would block real network access.

PATH DEPENDENCY (Codex review): the enable_socket marker is applied by a
conftest.py hook that matches on the string "tests/integration" in the
item fspath. Moving this test file outside tests/integration/ would
silently remove the marker and the global --disable-socket gate would
block every real-network call with SocketBlockedError. The test
`test_test_module_lives_under_tests_integration` at the bottom of this
module asserts the file remains under tests/integration/ so the
invariant is loud, not silent.

Content-tolerance philosophy:
  - Ticker entities (Yahoo RSS): assert staleness='fresh' only. Yahoo RSS
    may legitimately return 0 entries for a valid ticker during off-hours
    (Research Open Question 2).
  - Topic entities (Google News RSS): assert staleness='fresh' AND at least
    one headline — Google aggregates hundreds of publishers and reliably
    returns matches for broad topics.
  - We never assert specific headline text — it changes every minute.

Regression guards:
  - test_rss_real_user_agent_prevents_yahoo_429 turns RED if _USER_AGENT
    is removed from rss_provider.py — because Yahoo will return 429 and
    the raise_for_status() path converts that to fetch_failed.
"""

from __future__ import annotations

import pathlib

from alphaswarm.ingestion import NewsSlice, RSSNewsProvider


async def test_rss_real_fetch_ticker_entity_returns_fresh_slice() -> None:
    """Yahoo Finance RSS routing for a ticker symbol.

    Research Open Question 2: Yahoo may return 0 entries for legitimate
    tickers (off-hours / rate-limit edge). We assert staleness='fresh'
    (fetch succeeded) NOT headline count."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert "AAPL" in result
    slice_ = result["AAPL"]
    assert isinstance(slice_, NewsSlice)
    assert slice_.staleness == "fresh", (
        f"AAPL Yahoo RSS fetch should be fresh; got {slice_.staleness}. "
        "If this fails repeatedly, either (a) Yahoo is rate-limiting the "
        "test environment (check UA + Pitfall 4), (b) Yahoo RSS URL "
        "template changed, or (c) feedparser parse regressed."
    )
    assert slice_.source == "rss"


async def test_rss_real_fetch_topic_entity_returns_fresh_slice_with_headlines() -> None:
    """Google News RSS routing for a non-ticker topic entity.

    Google aggregates hundreds of publishers; 'EV battery' reliably returns
    many matches. If this assertion fails, either the Google News RSS URL
    template changed or quote_plus encoding is broken."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["EV battery"])
    assert "EV battery" in result
    slice_ = result["EV battery"]
    assert slice_.staleness == "fresh"
    assert len(slice_.headlines) >= 1, (
        "Google News aggregation should return at least one EV battery "
        "headline. If this regresses, check quote_plus encoding and "
        "the Google News RSS URL template."
    )
    # Entity filter is case-insensitive substring match; 'ev battery' must
    # appear (case-insensitive) in every returned headline.
    needle = "ev battery"
    for headline in slice_.headlines:
        assert needle in headline.lower(), (
            f"Entity filter regression — headline {headline!r} does not "
            f"contain case-insensitive 'ev battery'"
        )


async def test_rss_real_fetch_geopolitical_entity_returns_fresh_slice() -> None:
    """Google News RSS routing for a geopolitical topic with hyphen —
    confirms quote_plus handles realistic seed-rumor entity shapes."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["US-Iran war"])
    assert result["US-Iran war"].staleness == "fresh"
    assert result["US-Iran war"].source == "rss"


async def test_rss_real_user_agent_prevents_yahoo_429() -> None:
    """Pitfall 4 regression guard — Yahoo 429s without a browser-like UA.

    If _USER_AGENT is deleted from rss_provider.py, Yahoo will return 429
    on this request and raise_for_status() will flip the slice to
    fetch_failed. Staleness='fresh' on this first-attempt fetch is the
    signal that the UA mitigation is live."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fresh", (
        "First-attempt Yahoo RSS fetch failed. Most likely cause: "
        "_USER_AGENT header removed or misapplied (Pitfall 4)."
    )


async def test_rss_real_mixed_batch_returns_fresh_for_all_entities() -> None:
    """One asyncio.gather batch handles both Yahoo and Google News endpoints
    through a shared httpx.AsyncClient — confirms the dual-source routing
    works inside a single get_headlines call."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL", "EV battery"])
    assert set(result.keys()) == {"AAPL", "EV battery"}
    assert result["AAPL"].staleness == "fresh"
    assert result["EV battery"].staleness == "fresh"


def test_test_module_lives_under_tests_integration() -> None:
    """Codex review — invariant: this module MUST live under tests/integration/
    so the conftest enable_socket auto-marker applies. If relocated, the
    other tests in this file would silently fail under --disable-socket."""
    here = pathlib.Path(__file__).resolve()
    assert "tests/integration" in str(here), (
        f"{here} is outside tests/integration/ — the enable_socket auto-marker "
        "from conftest.py will not apply and the global --disable-socket gate "
        "will block real-network fetches. Move this file back under "
        "tests/integration/."
    )
