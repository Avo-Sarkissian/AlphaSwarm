// @vitest-environment happy-dom
import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BracketDeepDive } from '../../components/bracket_deep';
import type { AgentView } from '../../types';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';

const agent = (id: string, bracket: string, display: string): AgentView =>
  ({ id, bracket, bracketDisplay: display, signal: 'buy', confidence: 0.7, flipped: 0, roundLastSpoke: null, thinking: false }) as unknown as AgentView;

beforeEach(() => {
  stubFetch([{ path: /\/api\/edges\//, body: { edges: [] } }]);
});
afterEach(() => vi.unstubAllGlobals());

describe('BracketDeepDive', () => {
  it('uses the registry color and filters members by wire key', () => {
    renderShell(
      <BracketDeepDive
        bracket={{ bracket: 'sell_side', display_name: 'Sell-Side' }}
        agents={[agent('sell_side_01', 'sell_side', 'Sell-Side'), agent('quants_01', 'quants', 'Quants')]}
        onClose={() => {}}
      />,
      { raw: wsSnapshot },
    );
    const pill = screen.getByText('Sell-Side', { selector: '.bd-bracket-pill' });
    expect(pill.getAttribute('style') ?? '').toMatch(/#42d690|rgb\(66, 214, 144\)/i);
    expect(screen.getByText('1 AGENTS')).toBeTruthy();
  });
});
