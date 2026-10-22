// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ConsensusRing, KpiStrip } from '../../components/panels';
import { makeAgent } from '../helpers/agents';

afterEach(cleanup);

const pendingRoster = Array.from({ length: 100 }, (_, i) =>
  makeAgent(`quants_${String(i + 1).padStart(2, '0')}`, null),
);

const mixed = [
  makeAgent('a_01', 'buy'), makeAgent('a_02', 'buy'), makeAgent('a_03', 'buy'),
  makeAgent('a_04', 'sell'), makeAgent('a_05', 'hold'),
  makeAgent('a_06', null), makeAgent('a_07', null), makeAgent('a_08', 'parse_error'),
];

function kpi(agents: ReturnType<typeof makeAgent>[]) {
  return <KpiStrip agents={agents} tps={0} mem={50} slots={0} slotsMax={8} elapsed={0} round={1} />;
}

describe('consensus panels while a round is in flight', () => {
  it('KPI strip: nobody decided yet reads 0/100 decided, not HOLD 100%', () => {
    render(kpi(pendingRoster));
    expect(screen.queryByText(/0\/100 decided/)).not.toBeNull();
    expect(screen.queryByText('HOLD')).toBeNull();
    expect(screen.queryByText('pending')).not.toBeNull();
  });

  it('KPI strip: percentage over decided agents, failures reported', () => {
    render(kpi(mixed));
    expect(screen.queryByText(/5\/8 decided · 1 failed/)).not.toBeNull();
    expect(screen.queryByText('60%')).not.toBeNull();
  });

  it('ring: shows PENDING at the start of a round', () => {
    render(<ConsensusRing agents={pendingRoster} />);
    expect(screen.queryByText('PENDING')).not.toBeNull();
    expect(screen.queryByText('HOLD')).toBeNull();
    expect(screen.queryByText('0/100 decided')).not.toBeNull();
  });

  it('ring: leader and share among decided agents', () => {
    render(<ConsensusRing agents={mixed} />);
    expect(screen.queryByText('BUY')).not.toBeNull();
    expect(screen.queryByText('60%')).not.toBeNull();
    expect(screen.queryByText('5/8 decided')).not.toBeNull();
  });
});
