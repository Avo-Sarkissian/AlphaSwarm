"""ISOL-01: Frozen stdlib dataclasses for holdings — zero I/O, zero dependencies.

REVIEW HIGH (2026-04-18): PortfolioSnapshot.holdings is tuple[Holding, ...], not
list[Holding, ...]. `@dataclasses.dataclass(frozen=True)` prevents attribute
reassignment but does NOT prevent in-place mutation of a list field (you can
still do `snap.holdings.append(...)`). Using a tuple makes the value graph
deeply immutable.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal


@dataclasses.dataclass(frozen=True)
class Holding:
    """A single position in a portfolio.

    Uses Decimal for qty and cost_basis — never float (Pitfall 5 in research).
    """

    ticker: str
    qty: Decimal
    cost_basis: Decimal | None = None


@dataclasses.dataclass(frozen=True)
class PortfolioSnapshot:
    """Immutable snapshot of a user's holdings at a point in time.

    account_number_hash is ALREADY SHA256-first-8 hashed per HOLD-04 policy;
    raw account numbers never enter this type.

    holdings is tuple[Holding, ...] (not list) — REVIEW HIGH: frozen dataclass
    does not deep-freeze; a list field would still allow append/extend/pop.
    """

    holdings: tuple[Holding, ...]
    as_of: datetime
    account_number_hash: str
