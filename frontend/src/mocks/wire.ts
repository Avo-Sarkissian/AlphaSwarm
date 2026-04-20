// KR-41.1-02: static signal-wire seed used by v2.jsx SignalWire component.
// Until the backend exposes /api/wire, this mock streams through the live ticker.

export interface SignalWireEvent {
  agent: string;
  source: string;
  query: string;
  result: string;
  used: boolean;
}

export const SIGNAL_WIRE_SEED: ReadonlyArray<SignalWireEvent> = [
  { agent: 'Q-03', source: 'yfinance', query: 'AAPL 1d OHLCV', result: '$218.40  -0.82%', used: true },
  { agent: 'I-04', source: 'newsapi', query: '"Anthropic" past 24h', result: '12 hits', used: true },
  { agent: 'M-06', source: 'fred', query: 'CPIAUCSL YoY', result: '3.2%', used: true },
  { agent: 'D-11', source: 'reddit', query: '/r/wsb top 25', result: '8 mentions $AAPL', used: false },
  { agent: 'U-02', source: 'edgar', query: 'AAPL 10-K FY2025', result: '14.2MB · cached', used: true },
  { agent: 'S-01', source: 'polygon', query: 'SPY L1 book', result: '578.40 × 12.4k', used: true },
  { agent: 'A-07', source: 'x_api', query: 'cashtag:$AAPL', result: '47 posts · -0.31', used: true },
  { agent: 'Q-08', source: 'fmp', query: 'AAPL DCF inputs', result: 'FCF yield 3.1%', used: true },
  { agent: 'M-02', source: 'fred', query: 'DGS10', result: '4.28%', used: true },
  { agent: 'I-09', source: 'reuters', query: 'topic:anthropic', result: '3 wire items', used: true },
  { agent: 'X-02', source: 'cryptopanic', query: 'BTC sentiment 1h', result: 'bear 0.61', used: false },
  { agent: 'D-05', source: 'x_api', query: 'cashtag:$NVDA', result: '122 posts · +0.18', used: true },
  { agent: 'P-03', source: 'fred', query: 'UNRATE', result: '3.9%', used: true },
  { agent: 'W-04', source: 'polygon', query: 'AAPL dark pool', result: '2.1M block', used: true },
  { agent: 'Q-05', source: 'yfinance', query: 'MSFT 5d', result: '$410.75  +0.31%', used: false },
  { agent: 'U-07', source: 'edgar', query: 'ANTH S-1 search', result: '0 results', used: false },
  { agent: 'A-03', source: 'newsapi', query: 'acquisition rumor', result: '4 hits', used: true },
  { agent: 'I-01', source: 'reuters', query: 'topic:fed', result: '7 wire items', used: true },
];
