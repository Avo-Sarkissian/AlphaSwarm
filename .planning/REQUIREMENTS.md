# Requirements: AlphaSwarm v6.0 Real Data + Advisory

*Requirements defined: 2026-04-18*
*Milestone: v6.0 Real Data + Advisory*

## Isolation (ISOL)

- [x] **ISOL-01**: `alphaswarm.holdings` stdlib frozen dataclasses (`Holding`, `PortfolioSnapshot`) with no pydantic/httpx/yfinance imports — Validated in Phase 37
- [x] **ISOL-02**: `alphaswarm.ingestion` pydantic v2 frozen+forbid models (`ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals`) with tuple-only collection fields and zero holdings fields — Validated in Phase 37
- [x] **ISOL-03**: importlinter forbidden contract with whitelist-only inversion; `uv run lint-imports` exits 0; drift-resistant coverage test — Validated in Phase 37
- [x] **ISOL-04**: Recursive PII redaction structlog processor in shared_processors before renderer — Validated in Phase 37
- [x] **ISOL-05**: `MarketDataProvider` and `NewsProvider` typing.Protocol classes with batch-first async signatures and StalenessState-typed failure slices — Validated in Phase 37
- [x] **ISOL-06**: pytest-socket global gate + `tests/integration/` conftest auto-applying `enable_socket` — Validated in Phase 37
- [x] **ISOL-07**: Four-surface holdings isolation canary (logs, Neo4j, WebSocket, prompts) with sentinel fixtures, representation variants, positive controls — Scaffolded in Phase 37, activates in Phase 41

## Ingestion (INGEST)

- [ ] **INGEST-01**: Real `YFinanceMarketDataProvider` implements `MarketDataProvider` protocol — `fetch_batch` returns `dict[str, MarketSlice]` with price, fundamentals, staleness; never raises
- [ ] **INGEST-02**: Real `NewsProvider` implementation — `fetch_headlines(entities)` returns entity-filtered headlines; never raises; integration tests use `enable_socket`
- [ ] **INGEST-03**: `ContextPacket` assembled pre-simulation from provider outputs and wired into seed injection prompt — agents receive grounded market context in Round 1

## Holdings (HOLD)

- [ ] **HOLD-01**: `HoldingsLoader.load(path)` reads Schwab CSV export and returns a `PortfolioSnapshot` with `Holding` tuples
- [ ] **HOLD-02**: Raw account numbers hashed via `sha256_first8` before storage in `PortfolioSnapshot`
- [ ] **HOLD-03**: `GET /api/holdings` REST endpoint served by `alphaswarm.web.routes.holdings` (the only web module permitted by importlinter to import `alphaswarm.holdings`)

## Advisory (ADVIS)

- [ ] **ADVIS-01**: `alphaswarm.advisory.synthesize(cycle_id, portfolio)` joins final-round bracket consensus signals against holdings tickers, returns ranked `AdvisoryItem` list
- [ ] **ADVIS-02**: `POST /api/advisory/{cycle_id}` triggers synthesis; uses orchestrator model with lifecycle serialization (no concurrent interviews/report generation)
- [ ] **ADVIS-03**: Vue `AdvisoryPanel.vue` renders advisory post-simulation; ISOL-07 canary activates confirming zero holdings leakage through all four surfaces

## Simulation Context (SIM)

- [ ] **SIM-04**: `run_simulation` accepts optional `context_packet: ContextPacket | None`; when provided, market prices and headlines appended to Round 1 agent prompts; backward-compatible default `None`

## Traceability

| REQ | Phase | Status |
|-----|-------|--------|
| ISOL-01 | Phase 37 | Complete |
| ISOL-02 | Phase 37 | Complete |
| ISOL-03 | Phase 37 | Complete |
| ISOL-04 | Phase 37 | Complete |
| ISOL-05 | Phase 37 | Complete |
| ISOL-06 | Phase 37 | Complete |
| ISOL-07 | Phase 37 (scaffolded) → Phase 41 (activated) | Partial |
| INGEST-01 | Phase 38 | Planned |
| INGEST-02 | Phase 38 | Planned |
| INGEST-03 | Phase 40 | Planned |
| HOLD-01 | Phase 39 | Planned |
| HOLD-02 | Phase 39 | Planned |
| HOLD-03 | Phase 39 | Planned |
| ADVIS-01 | Phase 41 | Planned |
| ADVIS-02 | Phase 41 | Planned |
| ADVIS-03 | Phase 41 | Planned |
| SIM-04 | Phase 40 | Planned |

---
*Last updated: 2026-04-18*
