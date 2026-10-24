import { describe, expect, it } from 'vitest';
import { graphCaption } from '../../viz/caption';

const base = { agentCount: 100, edgeCount: 0, edgesRound: null, roundNum: 1, loading: false };

describe('graphCaption', () => {
  it('explains round 1', () => {
    expect(graphCaption(base)).toBe('Round 1: agents decide independently. Peer influence starts in round 2.');
  });

  it('waits for a later round whose citations are not written yet', () => {
    expect(graphCaption({ ...base, roundNum: 2 })).toBe("Waiting for round 2's citations…");
  });

  it('says loading, then empty, for a round with an edge target', () => {
    expect(graphCaption({ ...base, roundNum: 3, edgesRound: 2, loading: true })).toBe('Loading round 2 citations…');
    expect(graphCaption({ ...base, roundNum: 3, edgesRound: 2 })).toBe('No citations in round 2.');
  });

  it('is silent with citations on screen or no agents', () => {
    expect(graphCaption({ ...base, edgeCount: 3, edgesRound: 2, roundNum: 3 })).toBeNull();
    expect(graphCaption({ ...base, agentCount: 0 })).toBeNull();
  });
});
