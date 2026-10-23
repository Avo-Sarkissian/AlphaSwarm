// Top bar: brand, phase, seed, run controls, model status and overlay buttons.
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Icon, type IconName } from '../components/Icon';
import { useConnection } from '../context/ConnectionContext';
import { ModelStatus } from '../features/dashboard/ModelStatus';
import { SEED_MAX_LENGTH } from '../lib/seed';
import type { ActiveModal } from './ModalHost';

function BrandMark() {
  const nodes: [number, number][] = [[8,2],[4,8],[12,8],[2,14],[8,14],[14,14],[6,11],[10,11]];
  return (
    <svg width="22" height="22" viewBox="0 0 16 16">
      {nodes.map((n, i) => (
        <circle key={i} cx={n[0]} cy={n[1]} r={i === 0 ? 2 : 1.3}
          fill={i === 0 ? 'var(--accent)' : 'var(--text)'} opacity={i === 0 ? 1 : 0.65} />
      ))}
      <path d="M8 2 L4 14 M8 2 L12 14 M6 11 L10 11" stroke="var(--text-3)" strokeWidth="0.4" fill="none" opacity="0.6" />
    </svg>
  );
}

const OVERFLOW_ITEMS: ReadonlyArray<{ label: string; icon: IconName; modal: ActiveModal }> = [
  { label: 'What-if Compare', icon: 'graph', modal: { kind: 'comingSoon', feature: 'whatif' } },
  { label: 'Multi-seed Synthesis', icon: 'bolt', modal: { kind: 'comingSoon', feature: 'multiseed' } },
  { label: 'Data Sources', icon: 'search', modal: { kind: 'dataSources' } },
  { label: 'Portfolio Stress Test', icon: 'doc', modal: { kind: 'comingSoon', feature: 'stress' } },
  { label: 'Advisory (v6.0)', icon: 'brief', modal: { kind: 'advisory' } },
  { label: 'Customize Brackets', icon: 'settings', modal: { kind: 'comingSoon', feature: 'brackets' } },
  { label: 'Cycle History', icon: 'replay', modal: { kind: 'cycles' } },
];

function OverflowMenu({ onOpen }: { onOpen: (modal: ActiveModal) => void }) {
  const [open, setOpen] = useState(false);
  const choose = (modal: ActiveModal) => {
    setOpen(false);
    onOpen(modal);
  };
  return (
    <div className="overflow-wrap">
      <button className="btn ghost-btn" title="More tools" data-active={open} onClick={() => setOpen((o) => !o)}>
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <circle cx="3" cy="7.5" r="1.3" fill="currentColor"/>
          <circle cx="7.5" cy="7.5" r="1.3" fill="currentColor"/>
          <circle cx="12" cy="7.5" r="1.3" fill="currentColor"/>
        </svg>
      </button>
      {open && (
        <div className="overflow-menu" onMouseLeave={() => setOpen(false)}>
          {OVERFLOW_ITEMS.map((item) => (
            <button key={item.label} className="overflow-item" onClick={() => choose(item.modal)}>
              <span className="overflow-item-icon"><Icon name={item.icon} /></span>
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export interface TopbarProps {
  phaseLabel: string;
  phaseState: 'live' | 'complete';
  seed: string;
  onSeedChange: (seed: string) => void;
  runControls: ReactNode;
  onOpen: (modal: ActiveModal) => void;
  onToggleShock: () => void;
}

export function Topbar({
  phaseLabel,
  phaseState,
  seed,
  onSeedChange,
  runControls,
  onOpen,
  onToggleShock,
}: TopbarProps) {
  const { lastFrame } = useConnection();
  const shockWindowOpen = lastFrame?.shockWindowOpen ?? false;
  return (
    <div className="topbar">
      <div className="brand">
        <BrandMark />
        <div className="brand-text">
          <span className="brand-name">AlphaSwarm</span>
          <span className="brand-sub">Mission Control</span>
        </div>
      </div>

      <div className="phase-pill" data-state={phaseState}>
        <span className="dot" />
        {phaseLabel}
      </div>

      <div className="seed-wrap">
        <div className="seed-input" style={{flex:1}}>
          <span className="prefix">SEED ⟶</span>
          <input
            value={seed}
            onChange={e => onSeedChange(e.target.value)}
            maxLength={SEED_MAX_LENGTH}
            placeholder="Seed rumor…"
            aria-label="Seed rumor"
          />
        </div>
      </div>

      {runControls}

      <ModelStatus />

      <div className="topbar-divider" />

      <button
        className="btn ghost-btn"
        onClick={onToggleShock}
        disabled={!shockWindowOpen}
        title={shockWindowOpen ? 'Inject shock event' : 'Shock window closed: a shock can only reach a later round'}
      >
        <Icon name="bolt" />
      </button>
      <button className="btn ghost-btn" onClick={() => onOpen({ kind: 'cycles' })} title="Watch / replay">
        <Icon name="replay" />
      </button>
      <button className="btn ghost-btn" onClick={() => onOpen({ kind: 'report', cycleId: null })} title="Simulation report">
        <Icon name="doc" />
      </button>
      <button className="btn ghost-btn" onClick={() => onOpen({ kind: 'settings' })} title="Settings">
        <Icon name="settings" />
      </button>

      <OverflowMenu onOpen={onOpen} />
    </div>
  );
}
