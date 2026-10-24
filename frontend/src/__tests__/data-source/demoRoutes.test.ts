import { describe, expect, it } from 'vitest';
import { DEMO_UNAVAILABLE_CODE } from '../../api/client';
import { parseCycleExport } from '../../data-source/cycleExport';
import { answerDemoRequest } from '../../data-source/demoRoutes';
import fixture from '../fixtures/cycle_export.json';

const exp = parseCycleExport(fixture);
const ID = encodeURIComponent(exp.cycle.cycle_id);

function json(method: string, url: string, current = 1): unknown {
  const answer = answerDemoRequest(exp, method, url, current);
  if (answer.kind === 'error') throw new Error(`unexpected ${answer.code}`);
  return answer.body;
}

describe('answerDemoRequest', () => {
  it('serves one round of citations', () => {
    expect(json('GET', `/api/cycles/${ID}/citations?round=2`)).toEqual({
      cycle_id: exp.cycle.cycle_id,
      round_num: 2,
      citations: exp.rounds[1]?.citations,
    });
    expect(json('GET', `/api/cycles/${ID}/citations?round=1`)).toMatchObject({ citations: [] });
  });

  it('serves the export and one agent history', () => {
    expect(json('GET', `/api/cycles/${ID}/export`)).toBe(exp);
    const history = json('GET', `/api/agents/quants_01/decisions?cycle_id=${ID}`) as { decisions: Array<{ round_num: number; cited_agents: string[] }> };
    expect(history.decisions.map((d) => d.round_num)).toEqual([1, 2, 3]);
    expect(Array.isArray(history.decisions[0]?.cited_agents)).toBe(true);
  });

  it('serves the report or a 404 when there is none', () => {
    expect(answerDemoRequest(exp, 'GET', `/api/report/${ID}`, 1)).toMatchObject({ kind: 'error', status: 404, code: 'report_not_found' });
    const withReport = { ...exp, report_markdown: '# Swarm report' };
    expect(answerDemoRequest(withReport, 'GET', `/api/report/${ID}`, 1)).toMatchObject({
      kind: 'json',
      body: { cycle_id: exp.cycle.cycle_id, content: '# Swarm report', sections: null },
    });
  });

  it('lists the recorded cycle and reports a healthy read-only backend', () => {
    const page = json('GET', '/api/replay/cycles?limit=20') as { cycles: Array<Record<string, unknown>>; next_before: null };
    expect(page.next_before).toBeNull();
    expect(page.cycles[0]).toMatchObject({ cycle_id: exp.cycle.cycle_id, round_count: 3, status: 'complete', agent_count: exp.roster.length });
    expect(json('GET', '/api/health')).toMatchObject({ status: 'ok', is_simulation_running: false });
  });

  it('seeks within the recorded rounds', () => {
    expect(answerDemoRequest(exp, 'POST', '/api/replay/round/9', 1)).toMatchObject({ kind: 'seek', round: 3 });
    expect(answerDemoRequest(exp, 'POST', '/api/replay/advance', 3)).toMatchObject({ kind: 'seek', round: 3 });
    expect(answerDemoRequest(exp, 'POST', `/api/replay/start/${ID}`, 2)).toMatchObject({ kind: 'seek', round: 1 });
  });

  it.each([
    ['GET', '/api/holdings'],
    ['GET', `/api/advisory/${ID}`],
    ['GET', '/api/settings'],
    ['POST', '/api/simulate/start'],
    ['POST', '/api/interview/quants_01'],
    ['POST', '/api/replay/stop'],
    ['GET', '/api/cycles/00000000-0000-4000-8000-0000000000ff/citations?round=2'],
  ])('refuses %s %s', (method, url) => {
    expect(answerDemoRequest(exp, method, url, 1)).toMatchObject({ kind: 'error', status: 503, code: DEMO_UNAVAILABLE_CODE });
  });
});
