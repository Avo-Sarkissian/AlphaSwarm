// The graph legend: one row per encoding currently on screen (legendItems).
import type { GraphLayout } from './layout';
import type { LegendItem, LegendKey } from './legendItems';

function Swatch({ k, layout }: { k: LegendKey; layout: GraphLayout }) {
  const box = { width: 18, height: 10, viewBox: '0 0 18 10', 'aria-hidden': true } as const;
  switch (k) {
    case 'buy':
    case 'sell':
    case 'hold':
      return <svg {...box}><circle cx={9} cy={5} r={4} fill={`var(--${k})`} /></svg>;
    case 'failed':
      return (
        <svg {...box}>
          <circle cx={9} cy={5} r={4} fill="var(--text-3)" />
          <path className="ig-fail-mark" d="M6.5,2.5 L11.5,7.5 M6.5,7.5 L11.5,2.5" />
        </svg>
      );
    case 'pending':
      return <svg {...box}><circle cx={9} cy={5} r={4} fill="var(--border-2)" /></svg>;
    case 'size':
      return (
        <svg {...box}>
          <circle cx={4} cy={5} r={2} fill="var(--text-2)" />
          <circle cx={12} cy={5} r={4.5} fill="var(--text-2)" />
        </svg>
      );
    case 'flip':
      return <svg {...box}><circle cx={9} cy={5} r={4} fill="none" stroke="var(--text-2)" strokeWidth={2} /></svg>;
    case 'ribbon':
      return <svg {...box}><path d="M1,5 L17,5" stroke="var(--text-2)" strokeWidth={4} /></svg>;
    case 'agent-edge':
    case 'edge-weight':
      return (
        <svg {...box}>
          <path d="M1,5 L13,5" stroke="var(--edge)" strokeWidth={k === 'edge-weight' ? 2.6 : 1.4} />
          <path d="M12,2 L17,5 L12,8 Z" fill="var(--edge)" />
        </svg>
      );
    case 'ego-in':
    case 'ego-out': {
      const colour = k === 'ego-in' ? 'var(--edge-in)' : 'var(--edge-out)';
      return layout === 'grid' ? (
        <svg {...box}><rect x={5} y={1} width={8} height={8} fill="none" stroke={colour} strokeWidth={2} /></svg>
      ) : (
        <svg {...box}>
          <path d="M1,5 L13,5" stroke={colour} strokeWidth={1.6} />
          <path d="M12,2 L17,5 L12,8 Z" fill={colour} />
        </svg>
      );
    }
    default:
      return <svg {...box} />;
  }
}

export function Legend({ items, layout }: { items: readonly LegendItem[]; layout: GraphLayout }) {
  if (items.length === 0) return null;
  return (
    <ul className="ig-legend" aria-label="Graph legend">
      {items.map((item) => (
        <li key={item.key} className="ig-legend-item" data-key={item.key}>
          <Swatch k={item.key} layout={layout} />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}
