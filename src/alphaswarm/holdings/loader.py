"""HOLD-01 / HOLD-02: HoldingsLoader reads Schwab CSV exports into PortfolioSnapshot.

This module is a submodule of `alphaswarm.holdings`. It is NOT added to
pyproject.toml [tool.importlinter] source_modules because the coverage test
(`tests/invariants/test_importlinter_coverage.py` line 101) already exempts
`alphaswarm.holdings.*` submodules. Adding it would BREAK
`test_source_modules_does_not_list_whitelisted_packages` (Research Pitfall 4).

D-01: Target CSV is 4 columns (account, symbol, shares, cost_basis_per_share), headers row 1.
D-02: Holding.cost_basis = Decimal(shares) * Decimal(cost_basis_per_share) — total, not per-share.
D-03: Multi-account rows collapse into a single merged PortfolioSnapshot.
D-04: All rows included — no money-market filtering.
HOLD-02: account_number_hash = sha256_first8("|".join(sorted(account_labels))).

Review resolutions (Codex + Gemini LOW concerns, 2026-04-19):
- BOM safety: open with encoding="utf-8-sig" so BOM-prefixed Schwab exports
  do not corrupt the first header (\\ufeffaccount → REQUIRED_COLUMNS failure).
- Same-ticker multi-account: emit separate Holding entries per CSV row; no
  summing, no weighted average. Phase 41 advisory expects per-row granularity
  for audit traceability (IRA vs taxable are tax-distinct lots).

Research Pitfall 1: NEVER Decimal(float) — always Decimal(string) for precision.
Research Pitfall 2: empty-body CSV must raise HoldingsLoadError before sha256_first8("")
  raises TypeError.
Research Pitfall 7: NEVER log raw Holding fields — ISOL-07 canary boundary.
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


def _as_of_from_path(path: Path) -> datetime:
    """Return tz-aware UTC datetime for `as_of`, with a race-safe fallback.

    Research Pattern 5: Path.stat().st_mtime converted to UTC reflects when
    the portfolio was last exported. If stat() raises after the file was
    successfully read (NFS race, permissions change), fall back to the current
    UTC time rather than letting the error propagate.
    """
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC)
    except OSError:
        log.warning("holdings_stat_fallback", path=str(path))
        return datetime.now(UTC)


class HoldingsLoader:
    """Loads a Schwab CSV export into a PortfolioSnapshot (HOLD-01, HOLD-02).

    Stateless — the single public method is a classmethod. The loader is pure
    Python stdlib (csv, decimal, pathlib, datetime) plus the shared
    sha256_first8 helper. It performs synchronous file I/O; the caller
    (FastAPI lifespan) invokes it via `asyncio.to_thread` so the event loop
    is never blocked at startup or request time.
    """

    @classmethod
    def load(cls, path: Path) -> PortfolioSnapshot:
        """Read the CSV at `path` and return a merged PortfolioSnapshot.

        Raises:
            HoldingsLoadError: on any failure (missing file, missing column,
                invalid numeric, empty data body, stat failure, etc.).
        """
        try:
            # Codex review LOW: encoding="utf-8-sig" silently strips a UTF-8
            # BOM if present (Schwab web exports can be BOM-prefixed). Under
            # plain "utf-8" the BOM would land in the first header name as
            # "\ufeffaccount" and fail REQUIRED_COLUMNS. "utf-8-sig" is a safe
            # default on non-BOM files (Python stdlib behavior).
            with path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise HoldingsLoadError("CSV is empty — no header row")
                missing = REQUIRED_COLUMNS - set(reader.fieldnames)
                if missing:
                    raise HoldingsLoadError(
                        f"CSV missing columns: {sorted(missing)}"
                    )
                rows = list(reader)
        except FileNotFoundError as exc:
            raise HoldingsLoadError(f"CSV not found: {path}") from exc
        except OSError as exc:
            raise HoldingsLoadError(f"Cannot read CSV: {exc}") from exc

        if not rows:
            # Pitfall 2: sha256_first8("") raises TypeError. Guard before hashing.
            raise HoldingsLoadError("CSV has no data rows")

        # Same-ticker multi-account contract (Gemini + Codex LOW): each CSV row
        # produces ONE Holding entry. If AAPL appears in both `individual` and
        # `roth_ira` the output tuple contains two AAPL Holdings. No summing,
        # no weighted averaging, no dedup — per-row granularity preserves audit
        # traceability (IRA vs taxable lots are tax-distinct).
        holdings_list: list[Holding] = []
        account_labels: set[str] = set()
        for row in rows:
            try:
                qty = Decimal(row["shares"])
                cost_per_share = Decimal(row["cost_basis_per_share"])
            except InvalidOperation as exc:
                raise HoldingsLoadError(
                    f"Invalid numeric value in row {row!r}: {exc}"
                ) from exc
            account_labels.add(row["account"])
            holdings_list.append(
                Holding(
                    ticker=row["symbol"],
                    qty=qty,
                    cost_basis=qty * cost_per_share,  # D-02 — total position cost
                )
            )

        # HOLD-02: account_number_hash is the sha256_first8 digest of the
        # sorted unique account labels joined with '|'. With the real CSV this
        # is sha256_first8("individual|roth_ira"). Guarded above: rows is
        # non-empty, so account_labels is non-empty, so the join is non-empty.
        account_hash = sha256_first8("|".join(sorted(account_labels)))

        as_of = _as_of_from_path(path)

        # Pitfall 7: NEVER log raw Holding fields (ticker/qty/cost_basis).
        # Count + sorted account labels only — the labels (individual/roth_ira)
        # are not raw account numbers, so logging them is safe.
        log.info(
            "holdings_loaded",
            path=str(path),
            count=len(holdings_list),
            accounts=sorted(account_labels),
        )

        return PortfolioSnapshot(
            holdings=tuple(holdings_list),  # PortfolioSnapshot requires tuple
            as_of=as_of,
            account_number_hash=account_hash,
        )
