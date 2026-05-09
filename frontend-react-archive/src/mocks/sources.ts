// KR-41.1-02: static data-sources + source-stats fixtures used by v2.jsx DataSourcesModal.
// Until the backend exposes /api/sources, the inspector modal renders from these constants.

export interface DataSource {
  id: string;
  group: 'market' | 'macro' | 'filings' | 'news' | 'social';
  label: string;
  desc: string;
  rate: string;
  latency: number;
}

export interface SourceStat {
  id: string;
  calls: number;
  cached: number;
  errors: number;
  lat_p50: number;
  lat_p95: number;
  bytes: string;
}

export const DATA_SOURCES: ReadonlyArray<DataSource> = [
  { id: 'yfinance',    group: 'market',  label: 'yfinance',       desc: 'Yahoo Finance price/volume',     rate: '2000/hr',  latency: 145 },
  { id: 'polygon',     group: 'market',  label: 'polygon.io',     desc: 'Real-time trades + aggregates',  rate: '5/s',      latency:  52 },
  { id: 'fred',        group: 'macro',   label: 'FRED',           desc: 'St. Louis Fed economic series',  rate: '120/min',  latency: 210 },
  { id: 'edgar',       group: 'filings', label: 'SEC EDGAR',      desc: '10-K / 10-Q / 8-K filings',      rate: '10/s',     latency: 380 },
  { id: 'newsapi',     group: 'news',    label: 'NewsAPI',        desc: 'Headline aggregator',            rate: '500/day',  latency: 190 },
  { id: 'reuters',     group: 'news',    label: 'Reuters Conn.',  desc: 'Wire feed',                      rate: 'unlimited', latency: 90 },
  { id: 'reddit',      group: 'social',  label: 'reddit',         desc: '/r/wsb + /r/investing',          rate: '60/min',   latency: 240 },
  { id: 'x_api',       group: 'social',  label: 'x.com',          desc: 'Filtered cashtag stream',        rate: '300/15m',  latency: 170 },
  { id: 'fmp',         group: 'market',  label: 'FMP',            desc: 'Financial Modeling Prep',        rate: '300/min',  latency: 165 },
  { id: 'cryptopanic', group: 'news',    label: 'CryptoPanic',    desc: 'Crypto news + sentiment',        rate: '500/day',  latency: 220 },
];

export const SOURCE_GROUP_COLOR: Record<string, string> = {
  market:  '#f5a524',
  macro:   '#8aa6ff',
  filings: '#b080ff',
  news:    '#5be7b8',
  social:  '#ff7aa8',
};

export const SOURCE_STATS: ReadonlyArray<SourceStat> = [
  { id: 'yfinance',    calls: 847, cached: 612, errors:  2, lat_p50: 140, lat_p95: 310, bytes: '4.2 MB' },
  { id: 'polygon',     calls: 412, cached:   0, errors:  0, lat_p50:  48, lat_p95: 110, bytes: '18.1 MB'},
  { id: 'fred',        calls: 156, cached: 134, errors:  0, lat_p50: 205, lat_p95: 420, bytes: '180 KB' },
  { id: 'edgar',       calls:  94, cached:  81, errors:  1, lat_p50: 360, lat_p95: 890, bytes: '52.8 MB'},
  { id: 'newsapi',     calls: 328, cached: 210, errors:  4, lat_p50: 180, lat_p95: 440, bytes: '2.1 MB' },
  { id: 'reuters',     calls: 201, cached:   0, errors:  0, lat_p50:  88, lat_p95: 190, bytes: '1.4 MB' },
  { id: 'reddit',      calls: 176, cached:  42, errors:  8, lat_p50: 240, lat_p95: 780, bytes: '3.2 MB' },
  { id: 'x_api',       calls: 512, cached:  18, errors: 12, lat_p50: 170, lat_p95: 520, bytes: '1.8 MB' },
  { id: 'fmp',         calls: 143, cached: 110, errors:  0, lat_p50: 160, lat_p95: 350, bytes: '720 KB' },
  { id: 'cryptopanic', calls:  58, cached:  40, errors:  0, lat_p50: 210, lat_p95: 460, bytes: '310 KB' },
];
