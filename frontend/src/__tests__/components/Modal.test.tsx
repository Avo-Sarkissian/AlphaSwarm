// @vitest-environment happy-dom
// The dialog primitive: semantics, Escape, focus in, focus restore, Tab trap,
// nested dialogs, IME composition, backdrop drags, and Escape layering with a
// pinned graph agent.
import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge } from '../../api/edges';
import { Modal, type ModalVariant } from '../../components/Modal';
import { InfluenceGraph } from '../../viz/InfluenceGraph';
import { rosterFromBrackets } from '../../viz/layout';
import { makeAgent } from '../helpers/agents';

afterEach(cleanup);

function Harness({ variant = 'dialog', onClose }: { variant?: ModalVariant; onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      <Modal
        open={open}
        title="Simulation report"
        variant={variant}
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
      >
        <button type="button" onClick={() => {}}>First</button>
        <input aria-label="Ask" data-autofocus />
        <button type="button" onClick={() => {}}>Last</button>
      </Modal>
    </>
  );
}

function openHarness(variant?: ModalVariant) {
  const onClose = vi.fn();
  render(<Harness variant={variant} onClose={onClose} />);
  const trigger = screen.getByRole('button', { name: 'Open' });
  trigger.focus();
  fireEvent.click(trigger);
  return { onClose, trigger };
}

describe('Modal', () => {
  it('renders nothing while closed', () => {
    render(<Modal open={false} title="Hidden" onClose={() => {}}>x</Modal>);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it.each(['dialog', 'takeover'] as const)('%s is a named, modal dialog', (variant) => {
    openHarness(variant);
    const dialog = screen.getByRole('dialog', { name: 'Simulation report' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
  });

  it('a drawer is a dialog that does not block the page', () => {
    openHarness('drawer');
    expect(screen.getByRole('dialog', { name: 'Simulation report' }).getAttribute('aria-modal')).toBeNull();
  });

  it('focuses the [data-autofocus] element, then restores focus to the opener on Escape', () => {
    const { onClose, trigger } = openHarness();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Ask' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('ignores Escape while an IME composition is active', () => {
    const { onClose } = openHarness();
    fireEvent.keyDown(document, { key: 'Escape', isComposing: true });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps Tab inside a blocking dialog', () => {
    openHarness();
    const first = screen.getByRole('button', { name: 'First' });
    const last = screen.getByRole('button', { name: 'Last' });
    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('closes on a press that starts on the backdrop, not on one that starts inside', () => {
    const { onClose } = openHarness();
    fireEvent.mouseDown(screen.getByRole('button', { name: 'First' }));
    expect(onClose).not.toHaveBeenCalled();
    const backdrop = screen.getByRole('dialog').parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape closes only the innermost of two open dialogs', () => {
    const outer = vi.fn();
    const inner = vi.fn();
    render(
      <Modal open title="Outer" onClose={outer}>
        <Modal open title="Inner" onClose={inner}>x</Modal>
      </Modal>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it('does not throw when the opener is gone by the time it closes', () => {
    function Vanishing() {
      const [open, setOpen] = useState(false);
      return open ? (
        <Modal open title="Report" onClose={() => setOpen(false)}>x</Modal>
      ) : (
        <button type="button" onClick={() => setOpen(true)}>Open</button>
      );
    }
    render(<Vanishing />);
    const trigger = screen.getByRole('button', { name: 'Open' });
    trigger.focus();
    fireEvent.click(trigger);
    expect(() => fireEvent.keyDown(document, { key: 'Escape' })).not.toThrow();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('Escape layering with the graph', () => {
  const agents = rosterFromBrackets().map((e) => makeAgent(e.id, 'buy', 0.6));
  const edges: Edge[] = [{ source_id: 'degens_02', target_id: 'quants_01', weight: 0.01 }];

  it('Escape closes an open dialog first and unpins only on the next press', () => {
    function WithDialog() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <InfluenceGraph agents={agents} edges={edges} edgesRound={2} roundNum={3} layout="clusters" allEdges={false} />
          <Modal open={open} title="Settings" onClose={() => setOpen(false)}>
            <button type="button" onClick={() => {}}>Save</button>
          </Modal>
        </>
      );
    }
    const { container } = render(<WithDialog />);
    fireEvent.click(container.querySelector('[data-agent="quants_01"]') as Element);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(container.querySelector('.ig-tooltip')).not.toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(container.querySelector('.ig-tooltip')).toBeNull();
  });
});
