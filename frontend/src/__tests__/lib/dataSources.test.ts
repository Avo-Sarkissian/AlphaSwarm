import { describe, expect, it } from 'vitest';
import { isErrorResult, recentFor, summarizeAudit } from '../../lib/dataSources';
import { AUDIT } from '../fixtures/audit';

describe('dataSources', () => {
  it('summarizes calls, cache hits, errors and use per source', () => {
    expect(summarizeAudit(AUDIT)).toEqual([
      { source: 'yfinance', calls: 2, cached: 0, errors: 1, cited: 1, lastTs: 1765432101.0 },
      { source: 'rss', calls: 1, cached: 1, errors: 0, cited: 1, lastTs: 1765432102.0 },
    ]);
  });

  it('lists a source newest first with a limit', () => {
    expect(recentFor(AUDIT, 'yfinance', 1).map((e) => e.query)).toEqual(['QQQX 1d OHLCV']);
  });

  it('recognizes error results', () => {
    expect([isErrorResult('error: timeout'), isErrorResult('ok'), isErrorResult('cached')]).toEqual([true, false, false]);
  });
});
