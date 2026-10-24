"""Market-context probe: the market block each benchmark seed produces (nothing persisted).

For every seed in scripts/benchmark_seeds.json the orchestrator parses the rumor
(inject_seed against a graph stub, so no Cycle is written), the swarm-side resolver
validates tickers (docs/DECISIONS.md#adr-ticker-resolution), and the real yfinance
and RSS providers build the block agents would see
(docs/DECISIONS.md#adr-market-context). One markdown row per seed.

Manual: needs the Ollama orchestrator, network and (for name resolution) the cached
SEC map. Only seed-rumor entities are queried; no portfolio data is read.

    uv run python scripts/context_probe.py [--seeds scripts/benchmark_seeds.json] [--show-block]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from alphaswarm.ingestion.rss_provider import RSSNewsProvider
from alphaswarm.ingestion.tickers import load_ticker_resolver
from alphaswarm.ingestion.yfinance_provider import YFinanceMarketDataProvider
from alphaswarm.market_context import assemble_market_context
from alphaswarm.seed import inject_seed
from alphaswarm.services.runtime import close_operation, open_runtime
from alphaswarm.settings import AppSettings
from alphaswarm.types import EntityType, SeedEntity

PROBE_CYCLE_ID: Final = "00000000-0000-4000-8000-00000000c0de"
DEFAULT_SEEDS: Final = Path(__file__).resolve().parent / "benchmark_seeds.json"


@dataclass(frozen=True)
class ProbeRow:
    seed_id: str
    companies: int
    resolved: tuple[str, ...]
    non_empty: bool
    price_lines: int
    headline_lines: int
    chars: int


class _NoWriteGraph:
    """Stands in for GraphStateManager in inject_seed: returns a fixed id, writes nothing."""

    async def create_cycle_with_seed_event(self, *args: object, **kwargs: object) -> str:
        return PROBE_CYCLE_ID


def summarize_block(seed_id: str, entities: Sequence[SeedEntity], block: str | None) -> ProbeRow:
    lines = (block or "").splitlines()
    return ProbeRow(
        seed_id=seed_id,
        companies=sum(1 for e in entities if e.type is EntityType.COMPANY),
        resolved=tuple(e.ticker for e in entities if e.ticker is not None),
        non_empty=bool(block),
        price_lines=sum(1 for line in lines if line.startswith("Price: ")),
        headline_lines=sum(1 for line in lines if line.startswith("  - ")),
        chars=len(block or ""),
    )


def markdown_table(rows: Sequence[ProbeRow]) -> str:
    out = [
        "| seed | companies | resolved tickers | block | price lines | headlines | chars |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r.seed_id} | {r.companies} | {', '.join(r.resolved) or '-'} | "
            f"{'yes' if r.non_empty else 'no'} | {r.price_lines} | {r.headline_lines} | {r.chars} |"
        )
    out.append(f"| non-empty | {sum(r.non_empty for r in rows)}/{len(rows)} |  |  |  |  |  |")
    return "\n".join(out)


async def probe(seeds: Sequence[Mapping[str, str]], *, show_block: bool) -> list[ProbeRow]:
    settings = AppSettings()
    resolver = await load_ticker_resolver(settings.resolve_path(settings.ticker_map_path))
    market, news = YFinanceMarketDataProvider(), RSSNewsProvider()
    rows: list[ProbeRow] = []
    async with open_runtime(settings, with_neo4j=False) as runtime:
        built = await runtime.inference.open_operation("simulation")
        try:
            for seed in seeds:
                # inject_seed owns the orchestrator load and unload (docs/DECISIONS.md#p5-d-07).
                _, parsed, _ = await inject_seed(
                    seed["rumor"],
                    settings,
                    built.orchestrator,
                    _NoWriteGraph(),  # type: ignore[arg-type]
                    ticker_resolver=resolver,
                )
                block = await assemble_market_context(PROBE_CYCLE_ID, parsed, market, news)
                rows.append(summarize_block(seed["id"], parsed.seed_event.entities, block))
                if show_block:
                    print(f"--- {seed['id']} ---\n{block or '(no block)'}\n")
        finally:
            await close_operation(built, teardown=False)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=Path, default=DEFAULT_SEEDS)
    parser.add_argument("--show-block", action="store_true")
    args = parser.parse_args(argv)
    seeds = json.loads(args.seeds.read_text(encoding="utf-8"))["seeds"]
    print(markdown_table(asyncio.run(probe(seeds, show_block=args.show_block))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
