import type { DataSourceAuditView } from '../../types';

/** Three fictional provider calls (reserved fictional tickers). */
export const AUDIT: DataSourceAuditView[] = [
  { ts: 1765432100.5, source: 'yfinance', query: 'ZZZT 1d OHLCV', result: 'ok', used: true },
  { ts: 1765432101.0, source: 'yfinance', query: 'QQQX 1d OHLCV', result: 'error: empty', used: false },
  { ts: 1765432102.0, source: 'rss', query: 'headlines:ZZZT', result: 'cached', used: true },
];
