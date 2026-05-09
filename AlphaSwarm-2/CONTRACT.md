# AlphaSwarm — Frontend ↔ Backend Data Contract
**Version:** 0.1 · **Date:** 2026-04-18 · **Owner:** Frontend (Claude Design) · **Audience:** Backend implementation (Claude Code)

This document is the source of truth for every data shape the AlphaSwarm frontend consumes. Build the backend against these shapes exactly — the UI treats missing or renamed fields as errors.

---

## 1. Transport

| Stream | Transport | Rate | Purpose |
|---|---|---|---|
| `state_updates` | WebSocket | 5 Hz | Per-agent state, consensus, telemetry |
| `signal_wire`   | WebSocket | on-event | Data-source API calls |
| `rationales`    | WebSocket | on-event | Agent rationale emissions |
| `cycles`        | REST      | on-demand | Cycle archive + report |
| `sources`       | REST      | on-demand | Data-source metadata + stats |
| `settings`      | REST      | on-demand | User config (thresholds, model, keys) |

All WebSockets emit JSON lines. Timestamps are ISO-8601 UTC.

---

## 2. Core types

### 2.1 Agent
```ts
interface Agent {
  id: string;                 // e.g. "Q-03"
  bracket: BracketKey;        // machine-readable
  bracketDisplay: string;     // UI label, e.g. "Quants"
  signal: Signal | null;      // null while thinking
  confidence: number;         // 0..1
  flipped: boolean;           // has changed signal since R1
  flipFrom?: Signal;          // prev signal if flipped
  thinking: boolean;          // currently in inference slot
  roundLastSpoke: 1|2|3|null;
}

type Signal = 'buy' | 'sell' | 'hold' | 'parse_error';
type BracketKey =
  | 'quants' | 'degens' | 'sovereigns' | 'macro' | 'suits'
  | 'insiders' | 'agents' | 'doom_posters' | 'policy_wonks' | 'whales';
```

### 2.2 Bracket summary
```ts
interface BracketSummary {
  key: BracketKey;
  display: string;
  count: number;              // agents in bracket
  buy: number; sell: number; hold: number;
  avgConfidence: number;      // 0..1
}
```

### 2.3 Rationale
```ts
interface Rationale {
  id: string;                 // unique event id
  ts: string;                 // ISO timestamp
  agentId: string;
  round: 1|2|3;
  signal: Signal;
  confidence: number;
  text: string;               // natural-language rationale
  citations: string[];        // agent IDs this rationale cites
  sources: string[];          // data-source IDs this rationale references
}
```

### 2.4 Signal-wire event
```ts
interface WireEvent {
  id: string;
  ts: string;
  agent: string;              // agent id
  source: SourceId;           // which data source
  query: string;              // human-readable query
  result: string;             // one-line summary (e.g. "+2.4% vs prev")
  used: boolean;              // was this cited in a rationale?
  latencyMs: number;
  cached: boolean;
}
```

### 2.5 Data source
```ts
interface DataSource {
  id: SourceId;
  label: string;              // "yfinance", "FRED", "SEC EDGAR"
  group: SourceGroup;
  desc: string;
  rate: string;               // display string, e.g. "120 req/min"
  latency: number;            // baseline ms
}
type SourceGroup = 'market' | 'macro' | 'filings' | 'news' | 'social';

interface SourceStats {
  id: SourceId;
  calls: number;
  cached: number;
  errors: number;
  lat_p50: number; lat_p95: number;
  bytes: string;              // "12.4 MB"
}
```

### 2.6 Cycle (archive entry)
```ts
interface Cycle {
  id: string;                 // "C_2026_0418_A1"
  startedAt: string;
  endedAt: string;
  seed: string;
  consensus: Signal;
  consensusPct: number;       // 0..100
  flips: number;
  durationSec: number;
  shocks: number;
  starred: boolean;
}
```

### 2.7 Report (full cycle detail)
```ts
interface Report {
  cycle: Cycle;
  rounds: Array<{ r: 1|2|3; buy: number; sell: number; hold: number }>;
  keyMoments: Array<{ ts: string; title: string; body: string }>;
  dissent: Array<{
    agentId: string; bracket: string;
    stance: Signal; confidence: number; note: string;
  }>;
  influence: Array<{ agentId: string; bracket: string; outDegree: number }>;
  dataSummary: { calls: number; cached: number; errors: number; bytes: string };
  followups: Array<{ title: string; body: string }>;
}
```

### 2.8 Settings
```ts
interface Settings {
  memoryThresholdPct: number;   // default 90
  inferenceSlots: number;       // default 8
  model: string;                // "llama3.3:70b"
  agentCount: number;           // default 100
  bracketWeights: Record<BracketKey, number>; // sum = 1
  keysTomlPath: string;
  telemetry: false;             // always false
}
```

---

## 3. `state_updates` envelope

Every frame the backend pushes:
```ts
interface StateFrame {
  ts: string;
  phase: 1|2|3|'done';
  running: boolean;
  agents: Agent[];                // all 100, every frame
  consensus: { buy: number; sell: number; hold: number; dominant: Signal };
  telemetry: {
    tps: number;                  // tokens/sec
    memMb: number;
    slotsUsed: number;
    slotsMax: number;
    elapsedSec: number;
  };
  edges: Array<[string, string]>; // active citation edges [from, to]
}
```

Full-frame is fine at 5Hz for 100 agents (~12KB/frame). No need for deltas in v1.

---

## 4. Control messages (frontend → backend)

```ts
type Command =
  | { type: 'start'; seed: string }
  | { type: 'stop' }
  | { type: 'inject_shock'; text: string }
  | { type: 'interview'; agentId: string; question: string }
  | { type: 'load_cycle'; id: string }           // replay
  | { type: 'update_settings'; patch: Partial<Settings> };
```

---

## 5. Lifecycle states

The UI switches view based on these states (already designed — see `v2.html` Tweaks → Demo state):

| State | Trigger | Frontend shows |
|---|---|---|
| `idle`      | no cycle running, seed empty                        | IdleState overlay |
| `seeding`   | `spawn_progress` events while agents load           | SeedingState stream |
| `live`      | `running: true`                                      | Force graph |
| `mempause`  | `telemetry.memMb / ramCeiling > 0.9`                 | MemoryPausedState |
| `error`     | fatal error event                                    | ErrorState + log |
| `done`      | `phase: 'done'`                                      | Final graph + Report available |

---

## 6. Invariants the UI assumes

1. **Agent IDs are stable** across rounds and cycles. `Q-03` in one cycle is the same persona in every cycle.
2. **100 agents, always.** Not 99, not 101. If you want variable counts, version the contract.
3. **Bracket counts fixed.** Quants=14, Degens=12, Sovereigns=8, Macro=12, Suits=10, Insiders=10, Agents=10, Doom-Posters=8, Policy Wonks=8, Whales=8.
4. **`consensus.dominant`** is whichever of buy/sell/hold has the plurality; ties broken toward `hold`.
5. **Timestamps strictly monotonic** within a cycle.
6. **Local-first.** No data leaves the machine except data-source API calls. No telemetry.

---

## 7. Error surfaces

Every WebSocket can emit:
```ts
interface ErrorEvent {
  type: 'error';
  severity: 'warn' | 'error' | 'fatal';
  code: string;               // "ollama_rpc", "parse_error", "memory_ceiling"
  agent?: string;
  message: string;
  retryable: boolean;
}
```
`fatal` transitions the UI to `ErrorState`.
`memory_ceiling` transitions to `MemoryPausedState`.

---

## 8. What the frontend does NOT need

These exist in the backend but the UI doesn't consume them:
- Raw LLM prompts or token streams (only the parsed rationale text)
- Neo4j query results (out-degree numbers are computed server-side)
- Embedding vectors
- Cache internals

Keep them off the wire.

---

## 9. Open questions for backend

1. Should `signal_wire` events include a correlation ID that links them back to the rationale they informed?
2. For replay mode — is `load_cycle` a live re-run or does the backend serve pre-recorded frames?
3. Settings reload — hot-apply or require `stop` then `start`?
4. Shock propagation — does the backend compute delay-per-agent, or does the frontend stagger it visually?

Answer these in a PR; update this doc.

---

## Appendix: field cross-reference

| UI surface | Types it reads |
|---|---|
| Force graph + brackets panel | `Agent`, `BracketSummary`, `StateFrame.edges` |
| Signal Wire ticker | `WireEvent` (stream) |
| Data Sources modal | `DataSource`, `SourceStats`, `WireEvent` (for recent queries) |
| Rationale Feed | `Rationale` (stream) |
| Interview modal | `Agent` + `Rationale[]` for that agent |
| Cycle History | `Cycle[]` |
| Report modal | `Report` |
| Settings | `Settings` |
| KPI strip | `StateFrame.telemetry`, `StateFrame.consensus` |

---
*End of contract. Version bumps require a PR and sign-off from both instances.*
