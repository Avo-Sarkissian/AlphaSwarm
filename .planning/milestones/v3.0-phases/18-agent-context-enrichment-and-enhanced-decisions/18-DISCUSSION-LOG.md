# Phase 18: Agent Context Enrichment and Enhanced Decisions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-06
**Phase:** 18-agent-context-enrichment-and-enhanced-decisions
**Areas discussed:** Prompt injection design, Bracket data slices, AgentDecision extension, News headlines (DATA-03)

---

## Prompt Injection Design

| Option | Description | Selected |
|--------|-------------|----------|
| Append to user_message | Format block prepended to rumor text; no changes to AgentWorker/dispatch_wave | ✓ |
| Second system message | Extra {role: system} message after persona system_prompt | |
| Per-agent contextdict in dispatch_wave | List of pre-formatted strings alongside peer_contexts | |

**User's choice:** Append to user_message

| Option | Description | Selected |
|--------|-------------|----------|
| New enrichment.py module | Dedicated module owning format_market_block() + build_enriched_user_message() | ✓ |
| Inside market_data.py | Add formatting to fetcher module | |
| Inline in simulation.py | No new module, formatting inline | |

**User's choice:** New enrichment.py module

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed char limit per bracket | Per-bracket-group MAX_MARKET_BLOCK_CHARS dict; truncate to fit | ✓ |
| Single global char cap | One cap for all brackets | |
| Tokenizer-validated budget | Async API roundtrip to count real tokens | |

**User's choice:** Fixed char limit per bracket

---

## Bracket Data Slices

| Option | Description | Selected |
|--------|-------------|----------|
| 3 slice groups + fallback | Technicals / Fundamentals / Earnings+Insider covering all 10 brackets | ✓ |
| Each bracket gets its own slice | 10 individual data configs | |

**User's choice:** 3 slice groups (Technicals: Quants/Degens/Whales; Fundamentals: Suits/Sovereigns/Policy Wonks; Earnings/Insider: Insiders/Macro/Agents/Doom-Posters)

| Option | Description | Selected |
|--------|-------------|----------|
| All tickers, same slice | Every agent sees all tickers formatted with their bracket slice | ✓ |
| Primary ticker only | Most relevant ticker per agent (highest relevance score) | |

**User's choice:** All tickers, same slice

---

## AgentDecision Extension

| Option | Description | Selected |
|--------|-------------|----------|
| One AgentDecision covers all tickers | Optional ticker, direction, expected_return_pct, time_horizon fields | |
| Per-ticker decision list | ticker_decisions: list[TickerDecision] on AgentDecision | ✓ |

**User's choice:** Per-ticker decision list

| Option | Description | Selected |
|--------|-------------|----------|
| Flat list on AgentDecision | TickerDecision model in types.py; ticker_decisions: list[TickerDecision] = [] | ✓ |
| Separate parse path | Second parse step extracting from rationale via regex | |

**User's choice:** Flat list on AgentDecision (TickerDecision frozen model)

| Option | Description | Selected |
|--------|-------------|----------|
| Free string, validated by Pydantic | time_horizon: str \| None; prompt instructs '1d'\|'1w'\|'1m'\|'3m'\|'6m'\|'1y' | ✓ |
| Strict enum (TimeHorizon) | TimeHorizon(str, Enum) with SHORT_TERM/MEDIUM_TERM/LONG_TERM | |

**User's choice:** Free string with prompt-guided values

---

## News Headlines (DATA-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — AV NEWS_SENTIMENT endpoint | Fetch headlines if AV key configured; inject into Earnings/Insider slice | ✓ |
| Defer to Phase 20 | Keep headlines[] empty; DATA-03 compliance moves to Report phase | |

**User's choice:** Fetch via AV NEWS_SENTIMENT in Phase 18

| Option | Description | Selected |
|--------|-------------|----------|
| 5 headlines, silent skip if no key | structlog warning omitted when key absent | |
| 10 headlines, warn if no key | Emit structlog WARNING when key absent or fetch fails | ✓ |

**User's choice:** 10 headlines, warn if AV key absent

---

## Claude's Discretion

- Exact char cap values per bracket group
- Market data block formatting style (key-value vs table vs prose)
- Whether `direction` reuses `SignalType` or a new enum
- Per-headline truncation length
- Test fixture approach for enrichment.py

## Deferred Ideas

- Tokenizer validation (one-time calibration test, not hot path)
- NEWS_SENTIMENT for Fundamentals brackets (Suits/Policy Wonks)
- Ticker MENTIONS edges to Neo4j Entity nodes
- Multi-day headline cache with market-hours awareness
