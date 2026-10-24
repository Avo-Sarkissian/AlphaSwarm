// @vitest-environment happy-dom
// Panel elements that act on click are real buttons: reachable with Tab,
// operable with Enter or Space, announced as buttons.
import type { ComponentProps } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BracketList, RationaleFeed } from '../../features/dashboard/panels';

type Row = ComponentProps<typeof BracketList>['summaries'][number];
type Feed = ComponentProps<typeof RationaleFeed>['rows'][number];

const ROW: Row = {
  bracket: 'quants',
  display_name: 'Quants',
  total: 12,
  buy_count: 6,
  sell_count: 3,
  hold_count: 3,
  color: '#6aa9ff',
};
const FEED: Feed = {
  seq: 1,
  agentId: 'quants_01',
  bracketDisplay: 'Quants',
  signal: 'buy',
  round: 2,
  text: 'ZZZT Holdings looks priced in after the QQQX Robotics news.',
  cites: ['sell_side_03'],
};

afterEach(cleanup);

describe('panel controls are buttons', () => {
  it('a bracket row is a button that opens its deep dive', () => {
    const onClick = vi.fn();
    render(<BracketList summaries={[ROW]} onClick={onClick} />);
    const row = screen.getByRole('button', { name: /Quants/ });
    expect(row.getAttribute('type')).toBe('button');
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledWith(ROW);
  });

  it('a rationale author and its cite chips are buttons', () => {
    const onAgentClick = vi.fn();
    const onCiteClick = vi.fn();
    render(<RationaleFeed rows={[FEED]} onAgentClick={onAgentClick} onCiteClick={onCiteClick} />);
    fireEvent.click(screen.getByRole('button', { name: 'quants_01' }));
    fireEvent.click(screen.getByRole('button', { name: '↳ sell_side_03' }));
    expect(onAgentClick).toHaveBeenCalledWith('quants_01');
    expect(onCiteClick).toHaveBeenCalledWith('sell_side_03');
  });
});
