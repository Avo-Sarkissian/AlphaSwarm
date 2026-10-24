// The dashboard's single overlay slot: at most one modal, drawer or takeover
// is open at a time, and opening one replaces the current one
// (docs/DECISIONS.md#adr-frontend-quant-terminal).
import type { ComponentProps, ReactNode } from 'react';
import { Modal, type ModalVariant } from '../components/Modal';
import { useAgents } from '../context/AgentsContext';
import { AdvisoryPanel } from '../features/advisory/AdvisoryPanel';
import { CycleBrowser } from '../features/cycles/CycleBrowser';
import { BracketDeepDive } from '../features/dashboard/BracketDeepDive';
import { ShockDrawer } from '../features/dashboard/ShockDrawer';
import { InterviewPanel } from '../features/interview/InterviewPanel';
import { ReportModal } from '../features/report/ReportModal';
import { Settings } from '../features/settings/Settings';
import { DataSourcesTakeover } from '../features/wire/DataSourcesTakeover';
import type { AgentView } from '../types';
import { COMING_SOON_COPY, ComingSoonModal, type ComingSoonKey } from './ComingSoonModal';

/** The bracket row the deep dive was opened from (a snapshot taken at click time). */
export type BracketTarget = ComponentProps<typeof BracketDeepDive>['bracket'];

export type ActiveModal =
  | { kind: 'none' }
  | { kind: 'settings' }
  | { kind: 'report'; cycleId: string | null } // null: the report modal picks its default cycle
  | { kind: 'advisory' }
  | { kind: 'dataSources' }
  | { kind: 'cycles' }
  | { kind: 'shock' }
  | { kind: 'interview'; agentId: string }
  | { kind: 'bracket'; bracket: BracketTarget }
  | { kind: 'comingSoon'; feature: ComingSoonKey };

export interface ModalHostProps {
  modal: ActiveModal;
  onOpen: (next: ActiveModal) => void;
  onClose: () => void;
}

type OpenModal = Exclude<ActiveModal, { kind: 'none' }>;

interface DialogSpec {
  title: string;
  variant: ModalVariant;
  panelClassName?: string;
}

/** Classes of the report's centred panel (moved here from ReportModal's own wrapper). */
const REPORT_PANEL = 'modal modal-big report-panel';

/** Accessible name and presentation of each overlay. */
function dialogSpec(modal: OpenModal): DialogSpec {
  switch (modal.kind) {
    case 'settings':
      return { title: 'Settings', variant: 'takeover' };
    case 'report':
      return { title: 'Simulation report', variant: 'dialog', panelClassName: REPORT_PANEL };
    case 'advisory':
      return { title: 'Portfolio advisory', variant: 'takeover' };
    case 'dataSources':
      return { title: 'Data sources', variant: 'takeover' };
    case 'cycles':
      return { title: 'Cycle history', variant: 'takeover' };
    case 'shock':
      return { title: 'Inject a shock', variant: 'drawer' };
    case 'interview':
      return { title: `Interview ${modal.agentId}`, variant: 'takeover' };
    case 'bracket':
      return { title: `${modal.bracket.display_name} bracket`, variant: 'takeover' };
    case 'comingSoon':
      return { title: COMING_SOON_COPY[modal.feature].title, variant: 'dialog', panelClassName: 'modal' };
  }
}

/** Remount the dialog (fresh focus handling) whenever the overlay or its subject changes. */
function modalKey(modal: OpenModal): string {
  if (modal.kind === 'interview') return `interview:${modal.agentId}`;
  if (modal.kind === 'bracket') return `bracket:${modal.bracket.bracket}`;
  return modal.kind;
}

export function ModalHost({ modal, onOpen, onClose }: ModalHostProps) {
  const { agents } = useAgents();
  if (modal.kind === 'none') return null;
  const content = overlayContent(modal, agents, onOpen, onClose);
  if (content === null) return null;
  const spec = dialogSpec(modal);
  return (
    <Modal
      key={modalKey(modal)}
      open
      title={spec.title}
      variant={spec.variant}
      panelClassName={spec.panelClassName}
      onClose={onClose}
    >
      {content}
    </Modal>
  );
}

function overlayContent(
  modal: OpenModal,
  agents: readonly AgentView[],
  onOpen: (next: ActiveModal) => void,
  onClose: () => void,
): ReactNode {
  switch (modal.kind) {
    case 'settings':
      return <Settings onClose={onClose} />;
    case 'report':
      return <ReportModal cycleId={modal.cycleId} onClose={onClose} />;
    case 'advisory':
      return <AdvisoryPanel onClose={onClose} />;
    case 'dataSources':
      return <DataSourcesTakeover onClose={onClose} />;
    case 'cycles':
      return (
        <CycleBrowser
          onClose={onClose}
          onOpenReport={(cycle) => onOpen({ kind: 'report', cycleId: cycle.cycle_id })}
        />
      );
    case 'shock':
      return <ShockDrawer onClose={onClose} />;
    case 'interview':
      // Checked on every render: an id that is not in the live roster opens nothing.
      return agents.some((a) => a.id === modal.agentId) ? (
        <InterviewPanel agentId={modal.agentId} onClose={onClose} />
      ) : null;
    case 'bracket':
      return (
        <BracketDeepDive
          bracket={modal.bracket}
          agents={agents.filter((a) => a.bracket === modal.bracket.bracket)}
          onAgentInterview={(agent) => onOpen({ kind: 'interview', agentId: agent.id })}
          onClose={onClose}
        />
      );
    case 'comingSoon':
      return <ComingSoonModal feature={modal.feature} onClose={onClose} />;
  }
}
