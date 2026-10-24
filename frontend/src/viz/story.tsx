// Round-story primitives for the influence graph (docs/DECISIONS.md#adr-hero-graph):
// edges keyed by direction so React keeps the ones that stay and only new
// citations draw in, nodes placed by a CSS transform so a layout change moves
// them smoothly, and a ring in the previous signal's colour for a flip.
import type { ReactNode, SVGProps } from 'react';
import type { Edge } from '../api/edges';
import { signalColor, signalLabel } from '../lib/signals';
import type { DecidedSignal } from '../types';

function classes(...lists: Array<string | undefined>): string {
  return [...new Set(lists.flatMap((list) => list?.split(/\s+/) ?? []).filter(Boolean))].join(' ');
}

export function edgeKey(edge: Pick<Edge, 'source_id' | 'target_id'>): string {
  return `${edge.source_id}->${edge.target_id}`;
}

type EdgePathProps = { edge: Edge; d: string } & Omit<SVGProps<SVGPathElement>, 'd' | 'ref' | 'children'>;

export function EdgePath({ edge, d, className, ...rest }: EdgePathProps) {
  const seen = edge.cited_signal ? ` (saw ${signalLabel(edge.cited_signal)})` : '';
  return (
    <path
      fill="none"
      {...rest}
      d={d}
      pathLength={1}
      data-edge={edgeKey(edge)}
      data-cited-signal={edge.cited_signal}
      className={classes('ig-edge ig-edge--draw', className)}
    >
      <title>{`${edge.source_id} cited ${edge.target_id}${seen}`}</title>
    </path>
  );
}

type NodeGroupProps = { id: string; x: number; y: number; children: ReactNode } & Omit<
  SVGProps<SVGGElement>,
  'transform' | 'style' | 'ref' | 'children'
>;

export function NodeGroup({ id, x, y, children, className, ...rest }: NodeGroupProps) {
  return (
    <g
      {...rest}
      data-agent={id}
      className={classes('ig-node', className)}
      style={{ transform: `translate(${x}px, ${y}px)` }}
    >
      {children}
    </g>
  );
}

export function FlipRing({ r, from }: { r: number; from: DecidedSignal }) {
  return (
    <circle className="ig-flip" r={r + 3} fill="none" stroke={signalColor(from)} strokeWidth={2}>
      <title>{`Flipped from ${signalLabel(from)}`}</title>
    </circle>
  );
}
