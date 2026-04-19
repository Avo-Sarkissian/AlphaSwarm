# Phase 39: Holdings Loader - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 39-holdings-loader
**Areas discussed:** CSV format, CSV path wiring, Endpoint response shape, Loading strategy

---

## CSV format

| Option | Description | Selected |
|--------|-------------|----------|
| Positions page download | Has preamble rows before real headers | |
| Individual account export | Clean CSV, headers at row 1 | |
| Check the folder | Inspect actual files in repo | ✓ |

**Finding:** Three CSVs exist in `Schwab/`: two raw Schwab position exports with preambles, and a hand-crafted `holdings.csv` with 4 columns (`account, symbol, shares, cost_basis_per_share`), no preamble, headers at row 1, mixed accounts.

---

### cost_basis field

| Option | Description | Selected |
|--------|-------------|----------|
| Total cost (shares × per_share) | Compute at load time | ✓ |
| Per-share cost basis | Store exactly what the CSV says | |

**User's choice:** Total cost — more useful for advisory math.

---

### Multi-account handling

| Option | Description | Selected |
|--------|-------------|----------|
| Single merged PortfolioSnapshot | All accounts collapsed into one | ✓ |
| One PortfolioSnapshot per account | list[PortfolioSnapshot] return type | |

**User's choice:** Single merged snapshot — advisory synthesis needs a unified view.

---

### Money-market positions (SWYXX)

| Option | Description | Selected |
|--------|-------------|----------|
| Skip cash/money-market | Filter SWYXX etc. | |
| Include all positions | Pass through as Holding | ✓ |

**User's choice:** Include all — downstream code decides what to do with them.

---

## CSV path wiring

| Option | Description | Selected |
|--------|-------------|----------|
| AppSettings env var | ALPHASWARM_HOLDINGS_CSV_PATH | ✓ |
| Hardcoded conventional path | Always reads Schwab/holdings.csv | |

**User's choice:** AppSettings env var — clean, 12-factor, testable.

---

### Default path

| Option | Description | Selected |
|--------|-------------|----------|
| Schwab/holdings.csv | Points to existing file | ✓ |
| data/holdings.csv | More generic location | |

**User's choice:** `Schwab/holdings.csv` — works out of the box.

---

## Endpoint response shape

| Option | Description | Selected |
|--------|-------------|----------|
| Full snapshot | account_number_hash + as_of + holdings list | ✓ |
| Minimal list only | Just array of holdings | |

**User's choice:** Full snapshot — Vue advisory panel will need all of this.

---

## Loading strategy

**Clarification exchange:** User asked what this question meant given the architecture (orchestrator has holdings, swarm has live data). Clarified: this question is purely about the FastAPI web server behavior for the REST endpoint — not simulation data flow. Holdings never enter the swarm regardless.

| Option | Description | Selected |
|--------|-------------|----------|
| Eager at lifespan startup | Parse once, cache on app.state | ✓ |
| Lazy per-request | Re-read CSV on every GET call | |

**User's choice:** Eager startup — CSV doesn't change while server runs; matches existing lifespan pattern.

---

## Claude's Discretion

- `as_of` timestamp derivation (file mtime vs datetime.now at load time)
- `account_number_hash` derivation from account label set (no raw Schwab account numbers in holdings.csv)
- HoldingsLoader as class with classmethod vs standalone function
- 503 response body structure for missing/malformed CSV
