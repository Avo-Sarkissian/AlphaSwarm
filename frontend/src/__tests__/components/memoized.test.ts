// @vitest-environment happy-dom
// Dashboard pieces that receive frame data are React.memo components, so an
// unchanged slice skips their render (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { describe, expect, it } from 'vitest';
import { GraphPane } from '../../features/dashboard/GraphPane';
import { BracketList, ConsensusRing, KpiStrip, RationaleFeed } from '../../features/dashboard/panels';
import { Viz } from '../../features/dashboard/Viz';

const MEMO = Symbol.for('react.memo');

function isMemo(component: unknown): boolean {
  return (
    typeof component === 'object' &&
    component !== null &&
    (component as { $$typeof?: symbol }).$$typeof === MEMO
  );
}

describe('memoized dashboard components', () => {
  it.each([
    ['Viz', Viz],
    ['GraphPane', GraphPane],
    ['BracketList', BracketList],
    ['RationaleFeed', RationaleFeed],
    ['KpiStrip', KpiStrip],
    ['ConsensusRing', ConsensusRing],
  ])('%s is wrapped in React.memo', (_name, component) => {
    expect(isMemo(component)).toBe(true);
  });
});
