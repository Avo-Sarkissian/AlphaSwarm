// The one dialog primitive: role="dialog", aria-modal for blocking variants,
// Escape closes the innermost open dialog, Tab stays inside, and focus returns
// to whatever opened it. Every overlay goes through this (app/ModalHost.tsx,
// RunConfirmModal); docs/DECISIONS.md#adr-frontend-quant-terminal.
import { useEffect, useId, useLayoutEffect, useRef } from 'react';
import type { ReactNode, RefObject } from 'react';

/** dialog: centred panel on a backdrop; takeover: full-screen child; drawer: non-blocking panel. */
export type ModalVariant = 'dialog' | 'takeover' | 'drawer';

export interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  /** Element to focus on open; otherwise `[data-autofocus]`, the first focusable element, or the dialog. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  variant?: ModalVariant;
  /** Classes of the centred panel ('dialog' variant only). */
  panelClassName?: string;
  children: ReactNode;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Open dialogs in opening order; only the innermost one reacts to keys. */
const openDialogs: Array<{ id: string; el: HTMLElement | null }> = [];

/** The innermost dialog: the newest one that does not contain another open dialog. */
function isInnermost(id: string): boolean {
  const leaves = openDialogs.filter(
    (d) => !openDialogs.some((o) => o !== d && o.el !== null && d.el?.contains(o.el)),
  );
  return leaves[leaves.length - 1]?.id === id;
}

export function Modal(props: ModalProps) {
  return props.open ? <OpenModal {...props} /> : null;
}

function OpenModal({
  title,
  onClose,
  initialFocusRef,
  variant = 'dialog',
  panelClassName = 'modal',
  children,
}: ModalProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const blocking = variant !== 'drawer';

  useLayoutEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  // Register, move focus inside, and give it back on close.
  useLayoutEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = dialogRef.current;
    openDialogs.push({ id, el: root });
    const target =
      initialFocusRef?.current ??
      root?.querySelector<HTMLElement>('[data-autofocus]') ??
      root?.querySelector<HTMLElement>(FOCUSABLE) ??
      root;
    target?.focus();
    return () => {
      const at = openDialogs.findIndex((d) => d.id === id);
      if (at >= 0) openDialogs.splice(at, 1);
      if (previous?.isConnected) previous.focus();
    };
  }, [id, initialFocusRef]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isInnermost(id)) return;
      if (e.key === 'Escape' && !e.isComposing) {
        e.preventDefault();
        closeRef.current();
      } else if (e.key === 'Tab' && blocking) {
        keepTabInside(e, dialogRef.current);
      }
    };
    // Capture phase: the dialog sees Escape before page-level listeners (graph unpin).
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [id, blocking]);

  const dialog = {
    ref: dialogRef,
    role: 'dialog' as const,
    'aria-modal': blocking ? true : undefined,
    'aria-label': title,
    tabIndex: -1,
  };
  if (variant === 'dialog') {
    return (
      <div
        className="modal-backdrop"
        role="presentation"
        // mousedown, not click: a text selection that ends on the backdrop must not close.
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) closeRef.current();
        }}
      >
        <div {...dialog} className={panelClassName}>
          {children}
        </div>
      </div>
    );
  }
  return (
    <div {...dialog} className={variant === 'takeover' ? 'modal-layer' : 'modal-drawer'}>
      {children}
    </div>
  );
}

function keepTabInside(e: KeyboardEvent, root: HTMLElement | null): void {
  if (!root) return;
  const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)];
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (!first || !last) {
    e.preventDefault();
    root.focus();
  } else if (!root.contains(active)) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && (active === first || active === root)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}
