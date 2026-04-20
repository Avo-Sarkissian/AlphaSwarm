"""ADVIS-01 synthesis engine — placeholder for Task 1 import surface.

The real implementation (prefetch, single LLM call, bounded retry, D-07 ranking)
lands in Task 2 of plan 41-01. This stub exists so alphaswarm.advisory.__init__
can expose `synthesize` in its public re-exports from Task 1 onward.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from alphaswarm.advisory.types import AdvisoryReport
from alphaswarm.holdings.types import PortfolioSnapshot

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient


async def synthesize(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    graph_manager: "GraphStateManager",
    ollama_client: "OllamaClient",
    orchestrator_model: str,
) -> AdvisoryReport:
    """Placeholder — real body lands in Task 2."""
    raise NotImplementedError("synthesize() is implemented in plan 41-01 Task 2")
