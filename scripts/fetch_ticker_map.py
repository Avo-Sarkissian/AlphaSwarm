"""Download the SEC company ticker map into the gitignored cache.

Manual, needs network (docs/DECISIONS.md#adr-ticker-resolution):

    uv run python scripts/fetch_ticker_map.py --user-agent "AlphaSwarm research <contact email>"

The SEC asks automated clients to name themselves and a contact in the
User-Agent. The value is only sent in this one request and never stored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Final

import httpx

from alphaswarm.fsutil import atomic_write_text
from alphaswarm.ingestion.tickers import TickerResolver
from alphaswarm.settings import AppSettings

SEC_URL: Final = "https://www.sec.gov/files/company_tickers.json"


async def fetch(user_agent: str, dest: Path, *, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Fetch, validate and atomically write the map; returns the usable ticker count."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), transport=transport) as client:
        response = await client.get(SEC_URL, headers={"User-Agent": user_agent, "Accept": "application/json"})
        response.raise_for_status()
    payload = response.json()
    resolver = TickerResolver.from_sec_payload(payload)  # raises ValueError before anything is written
    dest.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(atomic_write_text, dest, json.dumps(payload, separators=(",", ":")), mode=0o644)
    return len(resolver.tickers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-agent", required=True, help='e.g. "AlphaSwarm research you@example.com"')
    parser.add_argument("--output", type=Path, default=None, help="default: AppSettings.ticker_map_path")
    args = parser.parse_args(argv)
    settings = AppSettings()
    dest = args.output if args.output is not None else settings.resolve_path(settings.ticker_map_path)
    count = asyncio.run(fetch(args.user_agent, dest))
    print(f"wrote {count} tickers to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
