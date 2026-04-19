"""HOLD-01 / HOLD-02: HoldingsLoader reads Schwab CSV exports into PortfolioSnapshot.

This module is a submodule of `alphaswarm.holdings`. It is NOT added to
pyproject.toml [tool.importlinter] source_modules because the coverage test
(`tests/invariants/test_importlinter_coverage.py` line 101) already exempts
`alphaswarm.holdings.*` submodules. Adding it would BREAK
`test_source_modules_does_not_list_whitelisted_packages` (Research Pitfall 4).

Implementation is filled in by Task 2; this file establishes the public
contract (HoldingsLoader class + HoldingsLoadError) that __init__.py
re-exports and tests reference.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.security.hashing import sha256_first8

log = structlog.get_logger(component="holdings.loader")

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"account", "symbol", "shares", "cost_basis_per_share"}
)


class HoldingsLoadError(Exception):
    """Raised when the CSV cannot be parsed into a PortfolioSnapshot.

    Caught by the FastAPI lifespan in Plan 02 so missing or malformed holdings
    data surfaces as a structured 503 instead of crashing the WebSocket loop
    (D-08, Phase 39 success criterion 4).
    """


class HoldingsLoader:
    """Loads a Schwab CSV export into a PortfolioSnapshot (HOLD-01, HOLD-02).

    Stateless — the single public method is a classmethod. Implementation
    lands in Task 2. At Task 1 the skeleton exists so __init__.py can
    re-export the public names and the test module in Task 3 can import
    them before the tests themselves are written.
    """

    @classmethod
    def load(cls, path: Path) -> PortfolioSnapshot:
        """Read the CSV at `path` and return a merged PortfolioSnapshot.

        Raises:
            HoldingsLoadError: on any failure (missing file, missing column,
                invalid numeric, empty data body, stat failure, etc.).
        """
        raise NotImplementedError("HoldingsLoader.load — Task 2")
