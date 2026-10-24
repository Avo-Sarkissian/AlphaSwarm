// The API answers one recorded cycle can give, computed in the browser
// (docs/DECISIONS.md#adr-cycle-export). Reads are served, replay seeks move the
// demo player, and anything that would change state or needs the models is
// refused with demo_unavailable.
import { DEMO_UNAVAILABLE_CODE, DEMO_UNAVAILABLE_MESSAGE } from '../api/client';
import type { CycleExport } from './cycleExport';

export type DemoAnswer =
  | { kind: 'json'; body: unknown }
  | { kind: 'seek'; round: number; body: unknown }
  | { kind: 'error'; status: number; code: string; message: string };

const UNAVAILABLE: DemoAnswer = { kind: 'error', status: 503, code: DEMO_UNAVAILABLE_CODE, message: DEMO_UNAVAILABLE_MESSAGE };
const AGENT_DECISIONS = /^\/api\/agents\/([a-z0-9_]+)\/decisions$/;
const SEEK = /^\/api\/replay\/round\/(\d+)$/;

const json = (body: unknown): DemoAnswer => ({ kind: 'json', body });

function seekTo(round: number, last: number): DemoAnswer {
  const shown = Math.min(Math.max(round, 1), last);
  return { kind: 'seek', round: shown, body: { status: 'ok', round_num: shown } };
}

function metric(exp: CycleExport, key: string): number | null {
  const value = exp.cycle.metrics[key];
  return typeof value === 'number' ? value : null;
}

function cycleItem(exp: CycleExport) {
  const final = exp.rounds.at(-1)?.decisions ?? [];
  const count = (signal: string) => final.filter((d) => d.signal === signal).length;
  const r2 = metric(exp, 'r2_flips');
  return {
    cycle_id: exp.cycle.cycle_id,
    created_at: exp.cycle.created_at,
    seed_rumor: exp.cycle.seed_rumor,
    round_count: exp.rounds.length,
    status: exp.cycle.status,
    final_buy: metric(exp, 'final_buy') ?? count('buy'),
    final_sell: metric(exp, 'final_sell') ?? count('sell'),
    final_hold: metric(exp, 'final_hold') ?? count('hold'),
    total_flips: r2 === null ? null : r2 + (metric(exp, 'r3_flips') ?? 0),
    total_seconds: metric(exp, 'total_seconds'),
    agent_count: exp.roster.length,
  };
}

function decisionsOf(exp: CycleExport, agentId: string) {
  return exp.rounds.flatMap((round) =>
    round.decisions
      .filter((d) => d.agent_id === agentId)
      .map((d) => ({
        round_num: round.round_num,
        signal: d.signal,
        confidence: d.confidence,
        sentiment: d.sentiment,
        rationale: d.rationale,
        cited_agents: d.cited_agent_ids,
      })),
  );
}

const HEALTH = {
  status: 'ok',
  simulation_phase: 'replay',
  memory_percent: 0,
  is_simulation_running: false,
  inference_mode: 'local',
  spent_usd: null,
  version: 'demo',
  components: {},
};

export function answerDemoRequest(exp: CycleExport, method: string, url: string, currentRound: number): DemoAnswer {
  const parsed = new URL(url, 'http://demo.invalid');
  const path = decodeURIComponent(parsed.pathname);
  const id = exp.cycle.cycle_id;
  const last = exp.rounds.length;
  const verb = method.toUpperCase();
  if (verb === 'GET') {
    if (path === '/api/health') return json(HEALTH);
    if (path === '/api/replay/cycles') return json({ cycles: [cycleItem(exp)], next_before: null });
    if (path === `/api/cycles/${id}/citations`) {
      const round = Number(parsed.searchParams.get('round'));
      const citations = exp.rounds.find((r) => r.round_num === round)?.citations ?? [];
      return json({ cycle_id: id, round_num: round, citations });
    }
    if (path === `/api/cycles/${id}/export`) return json(exp);
    if (path === `/api/report/${id}`) {
      return exp.report_markdown === null
        ? { kind: 'error', status: 404, code: 'report_not_found', message: 'This cycle has no report.' }
        : json({ cycle_id: id, content: exp.report_markdown, generated_at: exp.cycle.created_at, sections: null });
    }
    const agent = AGENT_DECISIONS.exec(path);
    if (agent?.[1] && parsed.searchParams.get('cycle_id') === id) {
      return json({ agent_id: agent[1], cycle_id: id, decisions: decisionsOf(exp, agent[1]) });
    }
    return UNAVAILABLE;
  }
  if (verb === 'POST') {
    const seek = SEEK.exec(path);
    if (seek?.[1]) return seekTo(Number(seek[1]), last);
    if (path === '/api/replay/advance') return seekTo(currentRound + 1, last);
    if (path === `/api/replay/start/${id}`) return { kind: 'seek', round: 1, body: { status: 'ok', cycle_id: id, round_num: 1 } };
  }
  return UNAVAILABLE;
}
