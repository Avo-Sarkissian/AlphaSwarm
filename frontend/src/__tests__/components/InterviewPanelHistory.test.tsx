// @vitest-environment happy-dom
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell as DashboardShell } from '../../app/AppShell';
import { InterviewPanel } from '../../features/interview/InterviewPanel';
import type { AgentView, RationaleView } from '../../types';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { ensureResizeObserver, requestedUrls, stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';
import { at } from '../helpers/at';

const CYCLE = '00000000-0000-4000-8000-0000000000a1';
const REPLAYED = '00000000-0000-4000-8000-0000000000b2';
const AGENT = (signal: string | null, confidence: number): AgentView =>
  ({ id: 'quants_01', bracket: 'quants', bracketDisplay: 'Quants', signal, confidence, flipped: 0, roundLastSpoke: null, thinking: signal === null }) as unknown as AgentView;
const DECISIONS = [
  { round_num: 1, signal: 'buy', confidence: 0.8, sentiment: 0.4, rationale: 'ZZZT deal looks accretive', cited_agents: [] },
  { round_num: 2, signal: 'sell', confidence: 0.6, sentiment: -0.2, rationale: 'Financing risk on QQQX', cited_agents: [] },
  { round_num: 3, signal: 'sell', confidence: 0.7, sentiment: -0.3, rationale: 'Stay short into the vote', cited_agents: [] },
];
const routes = (decisions = DECISIONS) => [
  { path: '/api/agents/quants_01/decisions', body: { agent_id: 'quants_01', cycle_id: CYCLE, decisions } },
  { path: /\/api\/edges\//, body: { edges: [] } },
  { path: '/api/replay/cycles', body: { cycles: [], next_before: null } },
  { method: 'POST', path: '/api/interview/quants_01', body: { response: 'Financing risk drove my sell.' } },
];
const COMPLETE = { phase: 'complete', mode: 'live' as const, roundNum: 3, numRounds: 3, cycleId: CYCLE };

beforeEach(() => ensureResizeObserver());
afterEach(() => vi.unstubAllGlobals());

describe('InterviewPanel', () => {
  it("shows each round's own stored signal and confidence", async () => {
    stubFetch(routes());
    renderShell(<InterviewPanel agentId="quants_01" onClose={() => {}} />, {
      raw: wsSnapshot,
      frame: { ...COMPLETE, agents: [AGENT('sell', 0.7)] },
    });
    expect(await screen.findByText('80%')).toBeTruthy();
    expect(screen.getByText('60%')).toBeTruthy();
    expect(screen.getByText('FLIPPED')).toBeTruthy();
    expect(screen.getByText(/Final round \(R3\) close: SELL, confidence 70%/)).toBeTruthy();

    fireEvent.click(screen.getByText('Rationale log'));
    const blocks = [...document.querySelectorAll('.itv-round-block')];
    expect(blocks.map((b) => b.querySelector('.rationale-signal')?.textContent)).toEqual(['BUY', 'SELL', 'SELL']);
    expect(blocks[1]?.textContent).toContain('Financing risk on QQQX');
  });

  it('marks the round in progress as live instead of reusing the current signal everywhere', async () => {
    stubFetch(routes(DECISIONS.slice(0, 2)));
    renderShell(<InterviewPanel agentId="quants_01" onClose={() => {}} />, {
      raw: wsSnapshot,
      frame: { phase: 'round_3', mode: 'live', roundNum: 3, numRounds: 3, cycleId: CYCLE, agents: [AGENT('hold', 0.55)] },
    });
    expect(await screen.findByText('R3 · live')).toBeTruthy();
    expect(screen.getByText('BUY')).toBeTruthy();
  });

  it('asks about the cycle on screen, including a replayed one', async () => {
    const mock = stubFetch(routes());
    renderShell(<InterviewPanel agentId="quants_01" onClose={() => {}} />, {
      raw: wsSnapshot,
      frame: { phase: 'replay', mode: 'replay', roundNum: 2, numRounds: 3, cycleId: REPLAYED, agents: [AGENT('sell', 0.6)] },
    });
    await waitFor(() => expect(requestedUrls(mock)).toContain(`/api/agents/quants_01/decisions?cycle_id=${REPLAYED}`));

    fireEvent.click(screen.getByText('What drove your signal?'));

    await screen.findByText('Financing risk drove my sell.');
    const post = mock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ message: 'What drove your signal?', cycle_id: REPLAYED });
  });
});

describe('dashboard interview flag', () => {
  it('opens one takeover no matter how many entry points are clicked', async () => {
    stubFetch(routes());
    const rationale = { seq: 1, agentId: 'quants_01', signal: 'buy', round: 1, text: 'ZZZT momentum', citations: [], sources: [], ts: 0 } as unknown as RationaleView;
    const { container } = renderShell(<DashboardShell />, {
      raw: wsSnapshot,
      frame: { ...COMPLETE, phase: 'round_2', roundNum: 2, agents: [AGENT('buy', 0.8)], rationales: [rationale] },
    });
    const node = container.querySelector('circle.node');
    expect(node).not.toBeNull();
    fireEvent.click(node!);
    fireEvent.click(at(screen.getAllByText('quants_01', { selector: '.rationale-agent' }), 0));
    await waitFor(() => expect(document.querySelectorAll('.itv-takeover')).toHaveLength(1));
  });
});
