// @vitest-environment happy-dom
// Legend rows and the agent card, rendered on their own.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge } from '../../api/edges';
import { AgentTooltip } from '../../viz/AgentTooltip';
import { egoNetwork } from '../../viz/edges';
import { Legend } from '../../viz/Legend';
import { legendItems } from '../../viz/legendItems';
import { makeAgent } from '../helpers/agents';

afterEach(cleanup);

const e = (source_id: string, target_id: string): Edge => ({ source_id, target_id, weight: 0.01 });

describe('Legend', () => {
  it('renders one labelled row per item, in order', () => {
    const items = legendItems({
      layout: 'clusters',
      edgeMode: 'ribbons',
      signals: new Set(['buy', 'parse_error']),
      sized: true,
      weighted: false,
      flips: false,
      withinCount: 0,
      hint: false,
    });
    render(<Legend items={items} layout="clusters" />);
    const rows = screen.getAllByRole('listitem');
    expect(rows.map((li) => li.textContent)).toEqual([
      'Buy',
      'Failed (parse error)',
      'Size: peers citing the agent',
      'Ribbon: citations between brackets, cited → citing',
    ]);
    expect(screen.getByRole('list', { name: 'Graph legend' })).toBeTruthy();
  });

  it('renders nothing without items', () => {
    const { container } = render(<Legend items={[]} layout="grid" />);
    expect(container.innerHTML).toBe('');
  });

  it('draws grid focus colours as outlines and graph focus colours as arrows', () => {
    const items = [{ key: 'ego-in' as const, label: 'Peers it cited' }];
    const grid = render(<Legend items={items} layout="grid" />);
    expect(grid.container.querySelector('rect')).not.toBeNull();
    cleanup();
    const graph = render(<Legend items={items} layout="radial" />);
    expect(graph.container.querySelector('rect')).toBeNull();
    expect(graph.container.querySelectorAll('path')).toHaveLength(2);
  });
});

describe('AgentTooltip', () => {
  const edges = [
    e('quants_01', 'sell_side_03'),
    e('degens_02', 'quants_01'),
    e('macro_01', 'quants_01'),
    e('algos_01', 'quants_01'),
    e('shorts_02', 'quants_01'),
  ];
  const ego = egoNetwork('quants_01', edges);

  it('says THINKING and hides confidence for a pending agent', () => {
    render(<AgentTooltip agent={makeAgent('quants_01', null)} x={100} y={100} canvasWidth={800} ego={ego} edgesRound={2} pinned={false} />);
    expect(screen.getByText('THINKING')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.getByText('Click to pin · Esc to unpin')).toBeTruthy();
  });

  it('lists who it cites and who cites it, capped at three ids', () => {
    render(<AgentTooltip agent={makeAgent('quants_01', 'buy', 0.72)} x={100} y={100} canvasWidth={800} ego={ego} edgesRound={2} pinned={false} />);
    expect(screen.getByText('72%')).toBeTruthy();
    expect(screen.getByText('Cited by (R2)').nextElementSibling?.textContent).toBe('4');
    expect(screen.getByText('degens_02, macro_01, algos_01 +1')).toBeTruthy();
    expect(screen.getByText('sell_side_03')).toBeTruthy();
  });

  it('explains that citations start in round 2', () => {
    render(<AgentTooltip agent={makeAgent('quants_01')} x={100} y={100} canvasWidth={800} ego={egoNetwork('quants_01', [])} edgesRound={null} pinned={false} />);
    expect(screen.getByText('Citations appear from round 2.')).toBeTruthy();
  });

  it('offers the interview only when pinned', () => {
    const onInterview = vi.fn();
    render(<AgentTooltip agent={makeAgent('quants_01')} x={100} y={100} canvasWidth={800} ego={ego} edgesRound={2} pinned onInterview={onInterview} />);
    fireEvent.click(screen.getByRole('button', { name: 'Interview quants_01 →' }));
    expect(onInterview).toHaveBeenCalledWith('quants_01');
  });

  it('opens to the left near the right edge of the canvas', () => {
    const { container } = render(<AgentTooltip agent={makeAgent('quants_01')} x={760} y={100} canvasWidth={800} ego={ego} edgesRound={2} pinned={false} />);
    const card = container.querySelector('.ig-tooltip') as HTMLElement;
    expect(parseFloat(card.style.left)).toBeLessThan(760);
  });
});
