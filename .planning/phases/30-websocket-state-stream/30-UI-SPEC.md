---
phase: 30
slug: websocket-state-stream
status: approved
reviewed_at: 2026-04-12
shadcn_initialized: false
preset: none
created: 2026-04-12
---

# Phase 30 -- UI Design Contract

> Visual and interaction contract for the WebSocket state stream. Phase 30 is a backend-only data plumbing phase with no browser rendering. This contract defines the **wire format** and **semantic conventions** that downstream visual phases (31-36) will consume.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | not applicable (Python backend phase) |
| Icon library | not applicable |
| Font | not applicable |

**Note:** Phase 30 produces no visual UI. The design system for the Vue 3 frontend will be established in Phase 31. This contract focuses on the JSON wire format and the semantic values embedded in the data stream.

---

## Spacing Scale

Not applicable -- Phase 30 has no visual layout. The standard 8-point scale (4, 8, 16, 24, 32, 48, 64) will be declared in Phase 31's UI-SPEC when the Vue SPA is built.

Exceptions: none

---

## Typography

Not applicable -- Phase 30 has no rendered text. Typography will be declared in Phase 31's UI-SPEC.

---

## Color

Phase 30 does not render colors, but it transmits **signal values** that downstream phases will map to colors. This contract locks the signal-to-color mapping so all visual phases use consistent semantics.

### Signal Color Semantics (Wire Values to Visual Mapping)

| Signal Value (in JSON) | Semantic Meaning | Downstream Color | Usage |
|------------------------|------------------|-------------------|-------|
| `"buy"` | Bullish signal | Green (#22C55E) | Agent node fill, grid cell, rationale badge |
| `"sell"` | Bearish signal | Red (#EF4444) | Agent node fill, grid cell, rationale badge |
| `"hold"` | Neutral signal | Gray (#6B7280) | Agent node fill, grid cell, rationale badge |
| `"parse_error"` | Inference failure | Amber (#F59E0B) | Agent node fill with warning indicator |
| `null` | Pending (no decision yet) | Slate (#94A3B8) | Agent node fill, muted/dimmed state |

### Phase Label Semantics (Wire Values to Visual Mapping)

| Phase Value (in JSON) | Display Label | Downstream Indicator |
|------------------------|---------------|----------------------|
| `"idle"` | Waiting for simulation | Muted status bar, pulsing dot |
| `"seeding"` | Analyzing rumor | Active spinner, amber status |
| `"round_1"` | Round 1 of 3 | Progress indicator 1/3 |
| `"round_2"` | Round 2 of 3 | Progress indicator 2/3 |
| `"round_3"` | Round 3 of 3 | Progress indicator 3/3 |
| `"complete"` | Simulation complete | Green checkmark, interview unlocked |
| `"replay"` | Replay mode | Distinct replay badge, step controls visible |

### 60/30/10 Color Split (Deferred)

Dominant, secondary, and accent colors are not applicable to Phase 30. They will be declared in Phase 31's UI-SPEC. The signal color semantics above are locked and Phase 31 must consume them as-is.

Accent reserved for: not applicable this phase

---

## Wire Format Contract

This is the primary deliverable of Phase 30's UI-SPEC. Every field, type, and nesting level is prescribed here. Downstream phases must parse this exact shape.

### WebSocket Endpoint

| Property | Value |
|----------|-------|
| URL | `ws://localhost:8000/ws/state` |
| Protocol | WebSocket (RFC 6455) |
| Direction | Server-to-client only (server push) |
| Tick rate | 5Hz (200ms intervals) |
| Authentication | None (local dev only, per D-10) |
| Client behavior | Connect, then enter receive loop; no client-to-server messages expected |

### JSON Payload Schema

Each tick broadcasts a single JSON object with this exact shape:

```json
{
  "phase": "round_1",
  "round_num": 1,
  "agent_count": 100,
  "elapsed_seconds": 42.7,
  "tps": 15.3,
  "agent_states": {
    "A_0": {"signal": "buy", "confidence": 0.85},
    "A_1": {"signal": "sell", "confidence": 0.62},
    "A_99": {"signal": null, "confidence": 0.0}
  },
  "bracket_summaries": [
    {
      "bracket": "quant",
      "display_name": "Quants",
      "buy_count": 6,
      "sell_count": 3,
      "hold_count": 1,
      "total": 10,
      "avg_confidence": 0.74,
      "avg_sentiment": 0.32
    }
  ],
  "governor_metrics": {
    "current_slots": 8,
    "active_count": 4,
    "pressure_level": "nominal",
    "memory_percent": 67.2,
    "governor_state": "running",
    "timestamp": 1712966400.0
  },
  "rationale_entries": [
    {
      "agent_id": "A_42",
      "signal": "buy",
      "rationale": "Strong institutional backing from Blackrock...",
      "round_num": 1
    }
  ]
}
```

### Field Reference

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `phase` | string enum | no | One of: `idle`, `seeding`, `round_1`, `round_2`, `round_3`, `complete`, `replay` |
| `round_num` | integer | no | Current round (0 when idle, 1-3 during simulation) |
| `agent_count` | integer | no | Always 100 |
| `elapsed_seconds` | float | no | Seconds since simulation start (0.0 when idle, frozen on complete) |
| `tps` | float | no | Tokens per second from Ollama inference (0.0 when idle) |
| `agent_states` | object | no | Map of agent_id to AgentState; empty object `{}` when idle |
| `agent_states.{id}.signal` | string enum or null | yes | One of: `buy`, `sell`, `hold`, `parse_error`, or `null` (pending) |
| `agent_states.{id}.confidence` | float | no | 0.0 to 1.0 |
| `bracket_summaries` | array | no | 10 BracketSummary objects (one per archetype); empty array `[]` when idle |
| `bracket_summaries[].bracket` | string | no | Bracket type key (e.g., `quant`, `degen`, `sovereign`) |
| `bracket_summaries[].display_name` | string | no | Human-readable bracket name (e.g., "Quants") |
| `bracket_summaries[].buy_count` | integer | no | Agents in this bracket with BUY signal |
| `bracket_summaries[].sell_count` | integer | no | Agents in this bracket with SELL signal |
| `bracket_summaries[].hold_count` | integer | no | Agents in this bracket with HOLD signal |
| `bracket_summaries[].total` | integer | no | Total agents in this bracket (always 10) |
| `bracket_summaries[].avg_confidence` | float | no | Mean confidence across bracket agents |
| `bracket_summaries[].avg_sentiment` | float | no | Mean sentiment across bracket agents (-1.0 to 1.0) |
| `governor_metrics` | object or null | yes | Null until governor emits first metrics |
| `governor_metrics.current_slots` | integer | no | Concurrency semaphore capacity |
| `governor_metrics.active_count` | integer | no | Currently running inference tasks |
| `governor_metrics.pressure_level` | string | no | Memory pressure classification |
| `governor_metrics.memory_percent` | float | no | System RAM usage percentage |
| `governor_metrics.governor_state` | string | no | Governor lifecycle state |
| `governor_metrics.timestamp` | float | no | Unix timestamp of metrics capture |
| `rationale_entries` | array | no | 0 to 5 RationaleEntry objects per tick; empty array `[]` when idle |
| `rationale_entries[].agent_id` | string | no | Short agent identifier (e.g., "A_42") |
| `rationale_entries[].signal` | string enum | no | One of: `buy`, `sell`, `hold`, `parse_error` |
| `rationale_entries[].rationale` | string | no | Rationale text, truncated to 50 characters |
| `rationale_entries[].round_num` | integer | no | Round number this rationale came from (1-3) |

### Payload Size

| State | Approximate Size | Bandwidth at 5Hz |
|-------|-----------------|-------------------|
| IDLE (empty) | ~0.3 KB | ~1.5 KB/s |
| Full (100 agents, 10 brackets, 5 rationales) | ~7.3 KB | ~36.5 KB/s |

---

## Copywriting Contract

Phase 30 has no rendered UI, but it transmits data that downstream phases will display. The copy conventions below are locked for all downstream consumers.

| Element | Copy |
|---------|------|
| Primary CTA | Not applicable (Phase 30 is backend-only; "Start Simulation" CTA belongs to Phase 32) |
| Empty state heading | No active simulation |
| Empty state body | Start a simulation to see live agent activity. The stream will update automatically. |
| Error state (WS disconnect) | Connection lost. Reconnecting... |
| Error state (WS failed) | Unable to connect to simulation server. Check that the server is running on port 8000. |
| Reconnection notice | Reconnected. Live data resumed. |
| IDLE phase display | Waiting for simulation |
| SEEDING phase display | Analyzing seed rumor... |
| ROUND_N phase display | Round {N} of 3 |
| COMPLETE phase display | Simulation complete |
| REPLAY phase display | Replay mode |

### Destructive Actions

None in Phase 30. The WebSocket is read-only (server push). No destructive user actions exist.

---

## Connection Lifecycle Contract

These behaviors are implemented in Phase 30 but visually rendered by Phase 31+.

| Event | Server Behavior | Expected Frontend Response |
|-------|----------------|---------------------------|
| Client connects | `ConnectionManager.connect()` creates per-client queue and writer task | Show "Connected" indicator; begin rendering snapshots |
| Broadcast tick | `connection_manager.broadcast(json_str)` pushes to all client queues | Parse JSON, update reactive state, re-render affected components |
| Client queue full | Drop oldest message in that client's queue (bounded at 100) | No visible effect; client continues receiving latest snapshots |
| Client disconnects | `ConnectionManager.disconnect()` cancels writer task, removes queue | Frontend detects close event, show reconnect UI |
| Server shutdown | Broadcaster task cancelled, all WebSocket connections closed | Frontend detects close event, show "Server stopped" state |
| Serialization error | Logged and skipped (tick is lost); next tick proceeds normally | No visible effect; at most a 200ms gap in updates |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not applicable |
| Third-party | none | not applicable |

**Note:** Phase 30 is a Python backend phase. No frontend component registries are involved.

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

## Notes for Downstream Phases

1. **Phase 31 (Vue SPA):** Must consume the wire format exactly as specified above. The `agent_states` map keys (`A_0` through `A_99`) are stable identifiers. Signal-to-color mapping is locked in the Color section.

2. **Phase 33 (Monitoring Panels):** The `bracket_summaries` array always contains exactly 10 objects (one per archetype). The `rationale_entries` array contains 0-5 entries per tick (destructive drain, not cumulative).

3. **Phase 35 (Agent Interview):** Interview streaming uses a separate WebSocket endpoint (not `/ws/state`). The `/ws/state` stream continues during interviews.

4. **All frontend phases:** The stream ticks at 5Hz during all phases including IDLE. Frontend code should not poll or request data; it receives pushes passively. Reconnection logic is the frontend's responsibility.

---

*Phase: 30-websocket-state-stream*
*Contract created: 2026-04-12*
*Source: CONTEXT.md (10 decisions), RESEARCH.md (architecture patterns), state.py (dataclass shapes)*
