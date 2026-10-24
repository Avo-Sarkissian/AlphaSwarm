// @vitest-environment happy-dom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AdvHoldingRow } from '../../features/advisory/AdvisoryParts';
import { holdingView } from '../../lib/advisoryView';

describe('AdvHoldingRow', () => {
  it('shows swarm evidence, the divergence marker and a cost-basis label', () => {
    const h = holdingView({
      ticker: 'ZZZT', consensus_signal: 'BUY', confidence: 0.62, rationale_summary: 'x',
      cost_basis_exposure: '1234.56', swarm_signal: 'BUY', swarm_support: 4, swarm_sentiment: 0.35,
      evidence_agent_ids: ['quants_01'], llm_signal: 'SELL', divergent: true,
    }, 1234.56);
    render(<AdvHoldingRow h={h} />);
    expect(screen.queryByText('4 agents · swarm BUY')).not.toBeNull();
    expect(screen.getByText('DIVERGES').getAttribute('title')).toBe('Orchestrator read SELL; swarm agents lean BUY');
    expect(screen.getByTitle('Cost basis, not market value')).not.toBeNull();
  });

  it('says when the swarm evidence is too thin', () => {
    const h = holdingView({
      ticker: 'QQQX', consensus_signal: 'BUY', confidence: 0.8, rationale_summary: 'x',
      cost_basis_exposure: '617.28', swarm_signal: null, swarm_support: 2, llm_signal: 'BUY',
    }, 617.28);
    render(<AdvHoldingRow h={h} />);
    expect(screen.queryByText('2 agents · insufficient swarm evidence')).not.toBeNull();
    expect(screen.queryByText('DIVERGES')).toBeNull();
  });
});
