// The dashboard's single overlay slot: at most one modal, drawer or takeover
// is open at a time, and opening one replaces the current one
// (docs/DECISIONS.md#adr-frontend-quant-terminal).
import type { ComponentProps } from 'react';
import { useAgents } from '../context/AgentsContext';
import { AdvisoryPanel } from '../features/advisory/AdvisoryPanel';
import { CycleBrowser } from '../features/cycles/CycleBrowser';
import { BracketDeepDive } from '../features/dashboard/BracketDeepDive';
import { ShockDrawer } from '../features/dashboard/ShockDrawer';
import { InterviewPanel } from '../features/interview/InterviewPanel';
import { ReportModal } from '../features/report/ReportModal';
import { Settings } from '../features/settings/Settings';
import { DataSourcesTakeover } from '../features/wire/DataSourcesTakeover';
import { ComingSoonModal, type ComingSoonKey } from './ComingSoonModal';

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

export function ModalHost({ modal, onOpen, onClose }: ModalHostProps) {
  const { agents } = useAgents();
  switch (modal.kind) {
    case 'none':
      return null;
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
    default: {
      const unreachable: never = modal;
      return unreachable;
    }
  }
}
