// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ConsensusRing, KpiStrip } from '../../features/dashboard/panels';
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
  return <KpiStrip agents={agents} tps={0} mem={50} slots={0} slotsMax={8} elapsed={0} round={1} numRounds={3} />;
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

  // happy-dom cannot lay out SVG text, so check the geometry: the widest
  // line, "100/100 decided", must fit the ring's inner chord at its baseline
  // (no glyph in it descends below the baseline).
  it('ring: the decided line stays inside the ring at a full roster', () => {
    const full = pendingRoster.map((a) => ({ ...a, signal: 'buy' as const, thinking: false }));
    const { container } = render(<ConsensusRing agents={full} />);
    const line = screen.getByText('100/100 decided');
    const ring = container.querySelector('circle') as SVGCircleElement;
    const inner = Number(ring.getAttribute('r')) - Number(ring.getAttribute('stroke-width')) / 2;
    const dy = Number(line.getAttribute('y')) - Number(ring.getAttribute('cy'));
    const chord = 2 * Math.sqrt(inner ** 2 - dy ** 2);
    // JetBrains Mono advances 0.6em per character.
    const width = (line.textContent ?? '').length * 0.6 * Number(line.getAttribute('font-size'));
    expect(width).toBeLessThanOrEqual(chord);
  });
});

describe('round progress', () => {
  it('KPI strip counts rounds against num_rounds', () => {
    render(
      <KpiStrip agents={[]} tps={0} mem={50} slots={0} slotsMax={8} elapsed={0} round={2} numRounds={2} />,
    );
    expect(screen.queryByText('Elapsed · R2/2')).not.toBeNull();
  });
});

describe('ConsensusRing net score', () => {
  it('shows PENDING when every agent failed or is still thinking', () => {
    render(<ConsensusRing agents={[makeAgent('quants_01', null), makeAgent('degens_01', 'parse_error')]} />);
    expect(screen.queryByText('PENDING')).not.toBeNull();
    expect(screen.queryByText('0/2 decided')).not.toBeNull();
  });

  it('leans by the confidence-weighted net score and shows the reach-weighted score', () => {
    render(
      <ConsensusRing
        agents={[
          makeAgent('sell_side_01', 'buy', 0.8), makeAgent('sell_side_02', 'buy', 0.8),
          makeAgent('sell_side_03', 'buy', 0.8), makeAgent('shorts_01', 'sell', 0.6),
          makeAgent('quants_01', 'hold', 0.5), makeAgent('degens_01', 'parse_error'),
          makeAgent('degens_02', null),
        ]}
      />,
    );
    expect(screen.queryByText('BUY')).not.toBeNull();
    expect(screen.queryByText('net +0.36')).not.toBeNull();
    expect(screen.queryByText('reach +0.42')).not.toBeNull();
    expect(screen.queryByText('5/7 decided')).not.toBeNull();
  });

  it('a low-conviction BUY plurality leans HOLD', () => {
    render(
      <ConsensusRing
        agents={[
          makeAgent('quants_01', 'buy', 0.2), makeAgent('quants_02', 'buy', 0.2),
          makeAgent('quants_03', 'buy', 0.2), makeAgent('quants_04', 'sell', 0.3),
          makeAgent('quants_05', 'hold', 0.9),
        ]}
      />,
    );
    expect(screen.queryByText('HOLD')).not.toBeNull(); // net = (0.6 - 0.3) / 5 = 0.06
    expect(screen.queryByText('net +0.06')).not.toBeNull();
  });
});
