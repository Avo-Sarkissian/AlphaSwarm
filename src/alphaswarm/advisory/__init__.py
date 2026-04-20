"""alphaswarm.advisory — post-simulation advisory synthesis (Phase 41, ADVIS-01).

This package is the SECOND permitted importer of alphaswarm.holdings (the first
being alphaswarm.web.routes.holdings). Per importlinter source_modules list in
pyproject.toml, alphaswarm.advisory is intentionally absent — making it allowed
to depend on alphaswarm.holdings. Do NOT add alphaswarm.advisory to that list.
"""
from alphaswarm.advisory.engine import synthesize
from alphaswarm.advisory.types import AdvisoryItem, AdvisoryReport, Signal

__all__ = ["AdvisoryItem", "AdvisoryReport", "Signal", "synthesize"]
