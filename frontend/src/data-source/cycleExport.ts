// TypeScript mirror of alphaswarm.export.CycleExport (format
// alphaswarm.cycle-export/1, docs/DECISIONS.md#adr-cycle-export). The backend
// golden fixture in __tests__/fixtures keeps the two in step.
export const CYCLE_EXPORT_SCHEMA = 'alphaswarm.cycle-export/1';

export interface ExportAgent {
  id: string;
  name: string;
  bracket: string;
  display_name: string;
  influence_weight_base: number;
  temperature: number;
}

export interface ExportDecision {
  agent_id: string;
  signal: string;
  confidence: number;
  sentiment: number;
  rationale: string;
  cited_agent_ids: string[];
  peer_ids: string[];
  control: boolean;
}

export interface ExportCitation {
  source_id: string;
  target_id: string;
  cited_signal: string;
}

export interface ExportRound {
  round_num: number;
  decisions: ExportDecision[];
  citations: ExportCitation[];
}

export interface ExportShock {
  text: string;
  injected_before_round: number;
}

export interface ExportCycleMeta {
  cycle_id: string;
  created_at: string;
  seed_rumor: string;
  overall_sentiment: number | null;
  num_rounds: number;
  status: string;
  metrics: Record<string, number | string | boolean>;
  manifest: Record<string, unknown> | null;
}

export interface CycleExport {
  schema: typeof CYCLE_EXPORT_SCHEMA;
  cycle: ExportCycleMeta;
  roster: ExportAgent[];
  rounds: ExportRound[];
  report_markdown: string | null;
  shocks: ExportShock[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Structural check of a parsed export; throws Error('cycle export: …') on a mismatch. */
export function parseCycleExport(raw: unknown): CycleExport {
  if (!isRecord(raw)) throw new Error('cycle export: not an object');
  if (raw.schema !== CYCLE_EXPORT_SCHEMA) throw new Error(`cycle export: unsupported schema ${String(raw.schema)}`);
  const { cycle, roster, rounds, shocks } = raw;
  if (!isRecord(cycle) || typeof cycle.cycle_id !== 'string') throw new Error('cycle export: cycle.cycle_id missing');
  if (!Array.isArray(roster) || roster.length === 0) throw new Error('cycle export: empty roster');
  const roundsOk =
    Array.isArray(rounds) &&
    rounds.length > 0 &&
    rounds.every((r) => isRecord(r) && typeof r.round_num === 'number' && Array.isArray(r.decisions) && Array.isArray(r.citations));
  if (!roundsOk) throw new Error('cycle export: malformed rounds');
  if (!Array.isArray(shocks)) throw new Error('cycle export: shocks missing');
  return raw as unknown as CycleExport;
}
