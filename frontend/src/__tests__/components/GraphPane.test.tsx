// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GraphPane } from '../../features/dashboard/GraphPane';
import type { AgentView } from '../../types';
import { makeAgent } from '../helpers/agents';
import { withFrame } from '../helpers/renderWithFrame';

const renders = vi.hoisted(() => ({ viz: 0 }));
const siblingRendered = vi.fn();

// The factory is hoisted above the imports, so it builds elements with
// createElement instead of JSX.
vi.mock('../../features/dashboard/Viz', async () => {
  const { createElement, memo } = await import('react');
  interface FakeVizProps {
    agents: readonly AgentView[];
    highlightId?: string;
    onAgentHover?: (agent: AgentView | null, event?: unknown) => void;
    onAgentClick?: (agent: AgentView) => void;
  }
  return {
    Viz: memo(function FakeViz({ agents, highlightId, onAgentHover, onAgentClick }: FakeVizProps) {
      renders.viz += 1;
      const first = agents[0];
      return createElement(
        'svg',
        { 'data-testid': 'viz', 'data-highlight': highlightId ?? '' },
        first
          ? createElement('circle', {
              'data-testid': 'node',
              onMouseEnter: (event: unknown) => onAgentHover?.(first, event),
              onMouseLeave: () => onAgentHover?.(null),
              onClick: () => onAgentClick?.(first),
            })
          : null,
      );
    }),
  };
});

const AGENTS = [makeAgent('quants_01'), makeAgent('degens_02')];

function Sibling() {
  siblingRendered();
  return <p>panel</p>;
}

// The tooltip reads the round count from the frame contexts, so the pane is
// rendered inside FrameProviders.
function Harness({ onAgentClick }: { onAgentClick: (agent: AgentView) => void }) {
  return (
    <div className="canvas-wrap">
      <GraphPane agents={AGENTS} layout="force" onAgentClick={onAgentClick} />
      <Sibling />
    </div>
  );
}

afterEach(() => {
  cleanup();
  renders.viz = 0;
  siblingRendered.mockClear();
});

describe('GraphPane', () => {
  it('shows the tooltip on hover and hides it on leave', () => {
    render(withFrame(<Harness onAgentClick={() => undefined} />));
    fireEvent.mouseEnter(screen.getByTestId('node'));
    expect(document.querySelector('.tooltip')?.textContent).toContain('quants_01');
    expect(screen.getByTestId('viz').getAttribute('data-highlight')).toBe('quants_01');
    fireEvent.mouseLeave(screen.getByTestId('node'));
    expect(document.querySelector('.tooltip')).toBeNull();
  });

  it('keeps hover state inside the pane', () => {
    render(withFrame(<Harness onAgentClick={() => undefined} />));
    const before = siblingRendered.mock.calls.length;
    fireEvent.mouseEnter(screen.getByTestId('node'));
    fireEvent.mouseLeave(screen.getByTestId('node'));
    expect(siblingRendered).toHaveBeenCalledTimes(before);
  });

  it('keeps the hover callback stable when the parent re-renders', () => {
    const onAgentClick = vi.fn();
    const { rerender } = render(withFrame(<Harness onAgentClick={onAgentClick} />));
    const before = renders.viz;
    rerender(withFrame(<Harness onAgentClick={onAgentClick} />));
    expect(renders.viz).toBe(before);
  });

  it('passes clicks through', () => {
    const onAgentClick = vi.fn();
    render(withFrame(<Harness onAgentClick={onAgentClick} />));
    fireEvent.click(screen.getByTestId('node'));
    expect(onAgentClick).toHaveBeenCalledWith(AGENTS[0]);
  });
});
