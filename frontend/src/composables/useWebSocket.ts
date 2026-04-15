import { ref, readonly, watch, type Ref } from 'vue'
import type { StateSnapshot, RationaleEntry } from '../types'

const DEFAULT_SNAPSHOT: StateSnapshot = {
  phase: 'idle',
  round_num: 0,
  agent_count: 100,
  agent_states: {},
  elapsed_seconds: 0,
  governor_metrics: null,
  tps: 0,
  rationale_entries: [],
  bracket_summaries: [],
}

export interface WebSocketState {
  snapshot: Readonly<Ref<StateSnapshot>>
  connected: Readonly<Ref<boolean>>
  reconnectFailed: Readonly<Ref<boolean>>
  /** Accumulated rationale entries (latest per agent, updated on each snapshot) */
  latestRationales: Readonly<Ref<Map<string, RationaleEntry>>>
  /** Ordered list of rationale entries (newest first), capped at 20. For the rationale feed panel. */
  allRationales: Readonly<Ref<RationaleEntry[]>>
}

/**
 * Composable: connect to ws://host/ws/state and expose reactive state.
 *
 * Reconnect strategy (UI-SPEC): exponential backoff 1s, 2s, 4s, 8s (max 8s).
 * reconnectFailed becomes true after 3 consecutive failures.
 * Resets on successful reconnection.
 */
export function useWebSocket(): WebSocketState {
  const snapshot = ref<StateSnapshot>({ ...DEFAULT_SNAPSHOT })
  const connected = ref(false)
  const reconnectFailed = ref(false)
  const latestRationales = ref<Map<string, RationaleEntry>>(new Map())
  const allRationales = ref<RationaleEntry[]>([])

  let ws: WebSocket | null = null
  let consecutiveFailures = 0
  let _reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function getWsUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws/state`
  }

  function connect(): void {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return
    }

    ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      connected.value = true
      reconnectFailed.value = false
      consecutiveFailures = 0
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data: StateSnapshot = JSON.parse(event.data)
        snapshot.value = data

        // Accumulate rationale entries by agent_id (keep latest per agent)
        if (data.rationale_entries && data.rationale_entries.length > 0) {
          const map = new Map(latestRationales.value)
          for (const entry of data.rationale_entries) {
            map.set(entry.agent_id, entry)
          }
          latestRationales.value = map

          // Accumulate rationale entries for feed panel (newest first, capped at 20)
          // REVIEW FIX (HIGH): Deduplicate by agent_id + round_num composite key.
          // Backend uses drain_rationales() (delta, not cumulative), but dedup
          // guards against WebSocket reconnection edge cases.
          const existingKeys = new Set(
            allRationales.value.map(e => `${e.agent_id}:${e.round_num}`)
          )
          const newEntries = data.rationale_entries.filter(
            (e: RationaleEntry) => !existingKeys.has(`${e.agent_id}:${e.round_num}`)
          )
          if (newEntries.length > 0) {
            allRationales.value = [...newEntries, ...allRationales.value].slice(0, 20)
          }
        }
      } catch {
        // Ignore malformed JSON
      }
    }

    ws.onclose = () => {
      connected.value = false
      ws = null
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }

  function scheduleReconnect(): void {
    if (_reconnectTimer !== null) {
      clearTimeout(_reconnectTimer)
      _reconnectTimer = null
    }
    consecutiveFailures++
    if (consecutiveFailures >= 3) {
      reconnectFailed.value = true
    }

    // Exponential backoff: 1s, 2s, 4s, 8s (max 8s)
    const delay = Math.min(1000 * Math.pow(2, consecutiveFailures - 1), 8000)
    _reconnectTimer = setTimeout(() => {
      _reconnectTimer = null
      connect()
    }, delay)
  }

  // Initial connection
  connect()

  // REVIEW FIX (HIGH): Clear accumulated rationales when simulation resets to idle.
  // Prevents stale entries from a previous run lingering in the feed.
  watch(() => snapshot.value.phase, (newPhase) => {
    if (newPhase === 'idle') {
      allRationales.value = []
    }
  })

  return {
    snapshot: readonly(snapshot) as Readonly<Ref<StateSnapshot>>,
    connected: readonly(connected),
    reconnectFailed: readonly(reconnectFailed),
    latestRationales: readonly(latestRationales) as Readonly<Ref<Map<string, RationaleEntry>>>,
    allRationales: readonly(allRationales) as Readonly<Ref<RationaleEntry[]>>,
  }
}
