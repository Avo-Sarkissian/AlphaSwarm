// Coming-soon overlay for the overflow-menu tools that are not built yet.
import { Icon } from '../components/Icon';

export type ComingSoonKey = 'whatif' | 'multiseed' | 'stress' | 'brackets';

export const COMING_SOON_COPY: Record<ComingSoonKey, { title: string; subtitle: string; body: string }> = {
  whatif: {
    title: 'What-if Compare',
    subtitle: 'COMPARE TWO SIMULATION SEEDS SIDE-BY-SIDE',
    body:
      'Run two seed rumors through the swarm in parallel and diff the resulting consensus, ' +
      'bracket distributions, and influence topology. Useful for testing how the same agents ' +
      'react to different framings of the same underlying event.\n\n' +
      'Requires backend support for paired-cycle dispatch and a dual-snapshot WS contract.',
  },
  multiseed: {
    title: 'Multi-seed Synthesis',
    subtitle: 'AGGREGATE SIGNAL ACROSS MULTIPLE SEEDS',
    body:
      'Submit a batch of related rumors (e.g. 10 paraphrasings of one event) and have the ' +
      'orchestrator synthesize a meta-advisory across all resulting cycles. Surfaces consensus ' +
      'that is stable across framings vs. seed-dependent artifacts.\n\n' +
      'Requires backend batch-orchestration and a synthesizer pass over N completed cycles.',
  },
  stress: {
    title: 'Portfolio Stress Test',
    subtitle: 'SHOCK YOUR PORTFOLIO THROUGH THE SWARM',
    body:
      'Inject a hypothetical macro/idiosyncratic shock mid-cycle and watch how each bracket ' +
      'updates. Returns a per-holding sensitivity map and worst-case drawdown estimates ' +
      'derived from the post-shock consensus distribution.\n\n' +
      'Requires the existing shock-injection wiring plus a portfolio-aware ' +
      'risk aggregator on the orchestrator side.',
  },
  brackets: {
    title: 'Customize Brackets',
    subtitle: 'ADJUST BRACKET COMPOSITION + PERSONAS',
    body:
      'Edit the 10 bracket archetypes (counts, risk profiles, persona prompts) before a run. ' +
      'Save and reload bracket presets to test how the swarm behaves with different ' +
      'compositions (e.g. all degens, no allocators).\n\n' +
      'Requires a persona-edit UI and a per-cycle bracket-override channel through the ' +
      'config layer.',
  },
};

export function ComingSoonModal({
  feature,
  onClose,
}: {
  feature: ComingSoonKey;
  onClose: () => void;
}) {
  const copy = COMING_SOON_COPY[feature];
  return (
    <>
      <div className="modal-head">
        <button className="btn ghost-btn" onClick={onClose} aria-label="Close">
          <Icon name="close" />
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ color: 'var(--text)', fontSize: 15, fontWeight: 600 }}>
            {copy.title}
          </div>
          <div
            className="label"
            style={{ marginTop: 2, color: 'var(--text-3)', letterSpacing: '0.12em' }}
          >
            {copy.subtitle}
          </div>
        </div>
        <span
          style={{
            padding: '3px 8px',
            border: '1px solid color-mix(in srgb, var(--accent) 35%, transparent)',
            borderRadius: 10,
            color: 'var(--accent)',
            fontSize: 10,
            letterSpacing: '0.12em',
          }}
        >
          COMING IN v6.x
        </span>
      </div>
      <div className="modal-body">
        {copy.body.split('\n\n').map((p, i) => (
          <p
            key={i}
            style={{
              color: 'var(--text-2)',
              fontSize: 13,
              lineHeight: 1.65,
              margin: i === 0 ? '0 0 12px' : '0',
            }}
          >
            {p}
          </p>
        ))}
      </div>
    </>
  );
}
