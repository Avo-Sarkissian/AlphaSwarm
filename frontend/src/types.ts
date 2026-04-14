export interface AgentState {
  signal: 'buy' | 'sell' | 'hold' | 'parse_error' | null
  confidence: number
}

export interface RationaleEntry {
  agent_id: string
  signal: string
  rationale: string
  round_num: number
}

export interface BracketSummary {
  bracket: string
  display_name: string
  buy_count: number
  sell_count: number
  hold_count: number
  total: number
  avg_confidence: number
  avg_sentiment: number
}

export interface GovernorMetrics {
  current_slots: number
  active_count: number
  pressure_level: string
  memory_percent: number
  governor_state: string
  timestamp: number
}

export interface StateSnapshot {
  phase: 'idle' | 'seeding' | 'round_1' | 'round_2' | 'round_3' | 'complete' | 'replay'
  round_num: number
  agent_count: number
  agent_states: Record<string, AgentState>
  elapsed_seconds: number
  governor_metrics: GovernorMetrics | null
  tps: number
  rationale_entries: RationaleEntry[]
  bracket_summaries: BracketSummary[]
}

export interface EdgeItem {
  source_id: string
  target_id: string
  weight: number
}

export interface EdgesResponse {
  edges: EdgeItem[]
}

/** Bracket archetype display names and their index (0-9) for node sizing */
export const BRACKET_ARCHETYPES = [
  { value: 'quants', display: 'Quants', radius: 5 },
  { value: 'degens', display: 'Degens', radius: 6 },
  { value: 'sovereigns', display: 'Sovereigns', radius: 7 },
  { value: 'macro', display: 'Macro', radius: 8 },
  { value: 'suits', display: 'Suits', radius: 9 },
  { value: 'insiders', display: 'Insiders', radius: 10 },
  { value: 'agents', display: 'Agents', radius: 11 },
  { value: 'doom_posters', display: 'Doom-Posters', radius: 12 },
  { value: 'policy_wonks', display: 'Policy Wonks', radius: 13 },
  { value: 'whales', display: 'Whales', radius: 14 },
] as const

/** Map bracket value -> radius for quick lookup */
export const BRACKET_RADIUS: Record<string, number> = Object.fromEntries(
  BRACKET_ARCHETYPES.map(b => [b.value, b.radius])
)

/** Map bracket value -> display name */
export const BRACKET_DISPLAY: Record<string, string> = Object.fromEntries(
  BRACKET_ARCHETYPES.map(b => [b.value, b.display])
)

/** Signal -> hex color mapping (D-09) */
export const SIGNAL_COLORS: Record<string, string> = {
  buy: '#22c55e',
  sell: '#ef4444',
  hold: '#6b7280',
  parse_error: '#374151',
}

/** Default color for agents with no signal yet */
export const PENDING_COLOR = '#374151'
