"""INGEST-02 unit tests — mocked httpx.AsyncClient + canned feed fixtures.

pytest-asyncio asyncio_mode='auto' is configured project-wide.

pytest-socket --disable-socket is active globally. These tests MUST NOT hit
real network — httpx.AsyncClient is replaced via monkeypatch. If a test
regresses and hits real network, pytest-socket raises SocketBlockedError.

Includes regression guards for 38-REVIEWS consensus fixes:
  #1 (HIGH) calendar.timegm (not the local-time stdlib converter) for
     published_parsed UTC conversion
  #2 (MEDIUM) explicit timeout on httpx.AsyncClient constructor
"""

from __future__ import annotations

import inspect
import pathlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from alphaswarm.ingestion import NewsProvider, NewsSlice, RSSNewsProvider

# --------- Canned RSS XML fixture builders ---------


def _struct_time_hours_ago(hours: float) -> time.struct_time:
    """Build a time.struct_time representing N hours ago (UTC)."""
    dt = datetime.now(UTC) - timedelta(hours=hours)
    return dt.timetuple()


def _make_feed_entries(entries: list[dict[str, Any]]) -> str:
    """Synthesize minimal RSS 2.0 XML for the given entry dicts.

    Each entry dict must have: 'title' (str), 'pub_dt' (datetime | None).
    """
    items = []
    for e in entries:
        pub = (
            f"    <pubDate>{e['pub_dt'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
            if e.get("pub_dt") is not None
            else ""
        )
        items.append(
            f"  <item>\n"
            f"    <title>{e['title']}</title>\n"
            f"{pub}\n"
            f"  </item>"
        )
    items_xml = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>\n'
        "  <title>Mock Feed</title>\n"
        f"{items_xml}\n"
        "</channel></rss>"
    )


# --------- Mock httpx.AsyncClient ---------


class _MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {"content-type": "application/rss+xml; charset=utf-8"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://mock"),
                response=httpx.Response(self.status_code),
            )


class _MockAsyncClient:
    """Replacement for httpx.AsyncClient.

    Usage: _MockAsyncClient.configure(responder=callable | dict); callable
    receives the url and returns a _MockResponse OR raises. Dict maps url->response.
    Recorded calls are available in .calls. Constructor kwargs recorded in
    .init_kwargs_log (list of dicts) — used by the explicit-timeout regression
    test to assert timeout=10.0 was passed to the AsyncClient constructor.
    """

    responder: Any = None  # set via configure()
    calls: list[dict[str, Any]] = []
    init_kwargs_log: list[dict[str, Any]] = []

    @classmethod
    def configure(cls, responder: Any) -> None:
        cls.responder = responder
        cls.calls = []
        cls.init_kwargs_log = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._init_args = args
        self._init_kwargs = kwargs
        type(self).init_kwargs_log.append(dict(kwargs))

    async def __aenter__(self) -> _MockAsyncClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _MockResponse:
        type(self).calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        responder = type(self).responder
        if callable(responder):
            maybe = responder(url)
            if isinstance(maybe, Exception):
                raise maybe
            assert isinstance(maybe, _MockResponse)
            return maybe
        if isinstance(responder, dict):
            resp = responder[url]
            assert isinstance(resp, _MockResponse)
            return resp
        raise AssertionError("_MockAsyncClient.responder not configured")


class _ForbidConstructionClient:
    """Assertion fixture: constructing this client fails the test — used to prove
    the empty-entity-list path never constructs an httpx client (Pitfall 9)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "httpx.AsyncClient was constructed despite empty entity list — "
            "Pitfall 9 guard regressed"
        )


# --------- URL routing (D-02) + T-38-01 URL injection mitigation ---------


async def test_url_routing_ticker_vs_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ticker ^[A-Z]{1,5}$ -> Yahoo RSS; everything else -> Google News RSS."""
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["AAPL", "EV battery"])
    urls = [c["url"] for c in _MockAsyncClient.calls]
    assert "https://finance.yahoo.com/rss/headline?s=AAPL" in urls
    assert any(
        u.startswith("https://news.google.com/rss/search?q=EV+battery") for u in urls
    )


async def test_url_injection_in_entity_is_quote_plus_encoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-38-01 mitigation — entity strings with & or = must be percent-encoded
    before URL interpolation. quote_plus converts '&' -> '%26' and '=' -> '%3D'."""
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["EV&cmd=drop"])
    url = _MockAsyncClient.calls[0]["url"]
    assert "&cmd=drop" not in url, f"entity injection leaked into URL: {url}"
    assert "EV%26cmd%3Ddrop" in url, f"quote_plus did not percent-encode: {url}"


async def test_ticker_regex_rejects_6_char_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regex ^[A-Z]{1,5}$ is strict — 6+ char symbols route through Google News."""
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["ABCDEF"])
    url = _MockAsyncClient.calls[0]["url"]
    assert url.startswith("https://news.google.com/rss/search?q=ABCDEF")


async def test_non_ticker_lowercase_entity_routes_to_google_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["apple inc"])
    url = _MockAsyncClient.calls[0]["url"]
    assert url.startswith("https://news.google.com/rss/search?q=apple+inc")


# --------- User-Agent header (Pitfall 4) ---------


async def test_user_agent_header_is_sent_on_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall 4 — Yahoo 429s without a browser-like User-Agent."""
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["AAPL", "MSFT", "US-Iran war"])
    assert len(_MockAsyncClient.calls) == 3
    for call in _MockAsyncClient.calls:
        assert call["headers"].get("User-Agent") == "Mozilla/5.0 AlphaSwarm/6.0"


# --------- REVIEWS consensus #2: explicit constructor timeout ---------


async def test_httpx_asyncclient_constructed_with_explicit_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """38-REVIEWS consensus #2 — the AsyncClient must be constructed with
    timeout=10.0 (_REQUEST_TIMEOUT_S). Without an explicit constructor timeout
    a hanging upstream would stall indefinitely without raising, defeating D-19."""
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    await provider.get_headlines(["AAPL"])
    assert len(_MockAsyncClient.init_kwargs_log) == 1, (
        "expected exactly one AsyncClient construction"
    )
    kwargs = _MockAsyncClient.init_kwargs_log[0]
    assert "timeout" in kwargs, (
        "httpx.AsyncClient constructed WITHOUT an explicit timeout kwarg — "
        "regressed 38-REVIEWS consensus #2; a slow upstream could hang the fetch"
    )
    assert kwargs["timeout"] == 10.0, (
        f"expected timeout=10.0 (_REQUEST_TIMEOUT_S), got {kwargs['timeout']!r}"
    )
    assert kwargs.get("follow_redirects") is True


# --------- Entity filter (D-03) + max_age_hours filter (Pitfall 3 + REVIEWS #1) ---------


async def test_get_headlines_returns_news_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — feed entries matching the entity come back as NewsSlice.headlines."""
    now = datetime.now(UTC)
    feed_xml = _make_feed_entries(
        [
            {"title": "Apple beats earnings", "pub_dt": now - timedelta(hours=1)},
            {"title": "Tesla leads EV race", "pub_dt": now - timedelta(hours=2)},
            {"title": "Apple stock rises on news", "pub_dt": now - timedelta(hours=3)},
        ]
    )
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["Apple"])
    assert isinstance(result["Apple"], NewsSlice)
    assert result["Apple"].staleness == "fresh"
    assert result["Apple"].source == "rss"
    assert set(result["Apple"].headlines) == {"Apple beats earnings", "Apple stock rises on news"}


async def test_entity_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-03 — case-insensitive substring match."""
    now = datetime.now(UTC)
    feed_xml = _make_feed_entries(
        [
            {"title": "Apple beats earnings", "pub_dt": now - timedelta(hours=1)},
            {"title": "Tesla leads EV race", "pub_dt": now - timedelta(hours=1)},
        ]
    )
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result_lower = await provider.get_headlines(["apple"])
    assert result_lower["apple"].headlines == ("Apple beats earnings",)
    result_upper = await provider.get_headlines(["TESLA"])
    assert result_upper["TESLA"].headlines == ("Tesla leads EV race",)


async def test_max_age_hours_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pitfall 3 — published_parsed struct_time converted to UTC datetime before filter.

    Uses calendar.timegm (REVIEWS #1) — treats struct_time as UTC, which the
    pub_dt.strftime(...+0000) format in _make_feed_entries is consistent with.
    """
    now = datetime.now(UTC)
    feed_xml = _make_feed_entries(
        [
            {"title": "Apple recent", "pub_dt": now - timedelta(hours=1)},
            {"title": "Apple midrange", "pub_dt": now - timedelta(hours=50)},
            {"title": "Apple ancient", "pub_dt": now - timedelta(hours=200)},
        ]
    )
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    r72 = await provider.get_headlines(["Apple"], max_age_hours=72)
    assert set(r72["Apple"].headlines) == {"Apple recent", "Apple midrange"}
    r24 = await provider.get_headlines(["Apple"], max_age_hours=24)
    assert r24["Apple"].headlines == ("Apple recent",)


async def test_max_age_hours_uses_calendar_timegm_not_local_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """38-REVIEWS consensus #1 — calendar.timegm treats published_parsed as UTC.

    If the provider regressed to the local-time stdlib converter (which treats
    the struct as LOCAL time), on a non-UTC host the computed age would be
    skewed by the local timezone offset (e.g., 6h entry reads as 6h + tz_offset).
    Here we force a 6h-old entry and verify it passes the max_age_hours=12
    filter — which only works if the UTC struct is correctly interpreted.
    """
    now = datetime.now(UTC)
    feed_xml = _make_feed_entries(
        [{"title": "Apple six hours old", "pub_dt": now - timedelta(hours=6)}]
    )
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    # Entry is 6h old; with max_age_hours=12 it MUST pass the filter on any host.
    # Local-time conversion on a non-UTC host could make the computed age ±24h,
    # which would push it outside max_age_hours=12 and cause this test to fail.
    result = await provider.get_headlines(["Apple"], max_age_hours=12)
    assert result["Apple"].headlines == ("Apple six hours old",), (
        "6h-old UTC entry should pass max_age_hours=12 — regression suggests "
        "local-time conversion is being used instead of calendar.timegm (REVIEWS #1)"
    )


async def test_undated_entry_passes_age_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries with no pubDate are kept regardless of max_age_hours."""
    feed_xml = _make_feed_entries(
        [{"title": "Apple undated", "pub_dt": None}]
    )
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["Apple"], max_age_hours=1)
    assert result["Apple"].headlines == ("Apple undated",)


# --------- D-19 never-raise ---------


async def test_get_headlines_fetch_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx.ConnectError must be caught and converted to fetch_failed slice."""

    def responder(_url: str) -> Any:
        return httpx.ConnectError("dns fail")

    _MockAsyncClient.configure(responder=responder)
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fetch_failed"
    assert result["AAPL"].headlines == ()
    assert result["AAPL"].source == "rss"


async def test_http_429_raises_for_status_and_returns_fetch_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall 4 regression guard — 429 from r.raise_for_status() becomes fetch_failed."""
    _MockAsyncClient.configure(responder=lambda url: _MockResponse("", status_code=429))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fetch_failed"


async def test_httpx_timeout_exception_returns_fetch_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense-in-depth — even with the explicit constructor timeout, if httpx
    raises a ReadTimeout the D-19 contract must still convert it to fetch_failed."""

    def responder(_url: str) -> Any:
        return httpx.ReadTimeout("upstream slow")

    _MockAsyncClient.configure(responder=responder)
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fetch_failed"


async def test_zero_entries_with_http_200_is_fresh_not_fetch_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Research Open Question 2 — legitimate ticker with 0 headlines is fresh,
    not fetch_failed. This is what Yahoo RSS may return during off-hours."""
    empty_feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(empty_feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fresh"
    assert result["AAPL"].headlines == ()


# --------- Pitfall 9 empty-list, duplicate entities ---------


async def test_empty_entity_list_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty entity list must short-circuit BEFORE constructing httpx.AsyncClient.
    The mock client raises in __init__ — if the guard regresses, the test fails."""
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _ForbidConstructionClient
    )
    provider = RSSNewsProvider()
    assert await provider.get_headlines([]) == {}


async def test_duplicate_entities_collapse_to_single_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL", "AAPL", "AAPL"])
    assert set(result.keys()) == {"AAPL"}


# --------- Async signature & Protocol conformance ---------


def test_get_headlines_is_async_def() -> None:
    provider = RSSNewsProvider()
    assert inspect.iscoroutinefunction(provider.get_headlines)


async def _news_consumer(p: NewsProvider) -> list[str]:
    """mypy conformance probe — RSSNewsProvider must structurally conform."""
    result = await p.get_headlines(["AAPL"], max_age_hours=48)
    return list(result.keys())


async def test_structural_conformance_against_news_provider_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed_xml = _make_feed_entries([])
    _MockAsyncClient.configure(responder=lambda url: _MockResponse(feed_xml))
    monkeypatch.setattr(
        "alphaswarm.ingestion.rss_provider.httpx.AsyncClient", _MockAsyncClient
    )
    provider = RSSNewsProvider()
    keys = await _news_consumer(provider)
    assert keys == ["AAPL"]


# --------- Module-level meta checks ---------


def test_rss_provider_module_imports_httpx_feedparser_but_not_yfinance() -> None:
    """Separation of concerns: rss_provider may use httpx + feedparser; must not import yfinance."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert "import httpx" in content
    assert "import feedparser" in content
    for banned in ("import yfinance", "from yfinance"):
        assert banned not in content, f"rss_provider.py must not contain '{banned}'"


def test_rss_provider_uses_fetch_failed_helper() -> None:
    """Pattern 3 — failure slices constructed via shared helper."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert "from alphaswarm.ingestion.providers import _fetch_failed_news_slice" in content
    assert "_fetch_failed_news_slice(entity, _SOURCE)" in content


def test_ticker_regex_is_strict_uppercase_1_to_5() -> None:
    """T-38-01 mitigation invariant — the ticker whitelist must match exactly ^[A-Z]{1,5}$."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert 'r"^[A-Z]{1,5}$"' in content


def test_rss_provider_never_parses_url_directly() -> None:
    """Pitfall 2 — feedparser.parse MUST receive response text, never a URL."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert "feedparser.parse(r.text)" in content
    assert "feedparser.parse(url)" not in content


def test_rss_provider_raises_for_status_before_parse() -> None:
    """38-REVIEWS Codex HIGH — r.raise_for_status() MUST be called BEFORE
    feedparser.parse(r.text). Otherwise a Yahoo 429 or Google error HTML
    page would be silently parsed as an empty-but-fresh feed (defeating
    Pitfall 4 coverage). This meta-invariant locks the ordering so a
    future refactor cannot silently reorder them."""
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert "r.raise_for_status()" in content, (
        "rss_provider.py must call r.raise_for_status() after client.get() "
        "so non-2xx responses become fetch_failed (Codex HIGH)"
    )
    i_status = content.index("r.raise_for_status()")
    i_parse = content.index("feedparser.parse(r.text)")
    assert i_status < i_parse, (
        "r.raise_for_status() MUST precede feedparser.parse(r.text) so a 429 "
        "cannot be silently parsed as an empty-but-fresh feed (Codex HIGH)"
    )


def test_rss_provider_uses_calendar_timegm_not_time_mktime() -> None:
    """38-REVIEWS consensus #1 regression guard — published_parsed is UTC-intended.

    calendar.timegm(published_parsed) correctly treats the struct as UTC.
    The local-time stdlib converter would treat it as LOCAL time and skew
    max_age_hours by the local timezone offset.
    """
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    content = src.read_text()
    assert "import calendar" in content, (
        "rss_provider.py must import calendar for timegm (REVIEWS #1)"
    )
    assert "calendar.timegm(published_parsed)" in content, (
        "rss_provider.py must use calendar.timegm for UTC struct_time -> epoch (REVIEWS #1)"
    )
    assert "time.mktime" not in content, (
        "rss_provider.py must NOT use time.mktime — it misinterprets UTC struct_time "
        "as local time (38-REVIEWS consensus #1)"
    )


def test_rss_provider_asyncclient_has_explicit_timeout_kwarg() -> None:
    """38-REVIEWS consensus #2 regression guard — httpx.AsyncClient constructor
    MUST receive timeout=_REQUEST_TIMEOUT_S so a hanging upstream cannot stall
    the provider without D-19 triggering.

    We verify the kwarg appears within the AsyncClient construction block by
    scanning the 4 lines following the 'httpx.AsyncClient(' token.
    """
    src = pathlib.Path(__file__).parent.parent / "src/alphaswarm/ingestion/rss_provider.py"
    lines = src.read_text().splitlines()
    found = False
    for idx, line in enumerate(lines):
        if "httpx.AsyncClient(" in line:
            # Look within this line + next 4 lines for the timeout kwarg
            block = "\n".join(lines[idx : idx + 5])
            if "timeout=_REQUEST_TIMEOUT_S" in block:
                found = True
                break
    assert found, (
        "httpx.AsyncClient(...) missing timeout=_REQUEST_TIMEOUT_S kwarg — "
        "a slow upstream would hang without raising, defeating D-19 (REVIEWS #2)"
    )
