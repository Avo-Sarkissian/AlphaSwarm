// Mock data module — exposes everything on window for other scripts.

const BRACKETS = [
  { value: 'quants',       display: 'Quants',       count: 10, radius: 5  },
  { value: 'degens',       display: 'Degens',       count: 20, radius: 6  },
  { value: 'sovereigns',   display: 'Sovereigns',   count: 10, radius: 7  },
  { value: 'macro',        display: 'Macro',        count: 10, radius: 8  },
  { value: 'suits',        display: 'Suits',        count: 10, radius: 9  },
  { value: 'insiders',     display: 'Insiders',     count: 10, radius: 10 },
  { value: 'agents',       display: 'Agents',       count: 15, radius: 11 },
  { value: 'doom_posters', display: 'Doom-Posters', count: 5,  radius: 12 },
  { value: 'policy_wonks', display: 'Policy Wonks', count: 5,  radius: 13 },
  { value: 'whales',       display: 'Whales',       count: 5,  radius: 14 },
];

const PREFIX = {
  quants: 'Q', degens: 'D', sovereigns: 'S', macro: 'M', suits: 'U',
  insiders: 'I', agents: 'A', doom_posters: 'X', policy_wonks: 'P', whales: 'W'
};

// deterministic PRNG so the layout is stable
function mulberry32(seed) {
  return function() {
    let t = (seed += 0x6D2B79F5) | 0;
    t = Math.imul(t ^ (t >>> 15), 1 | t);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildAgents(round, sigMix) {
  const rand = mulberry32(42);
  const agents = [];
  let idx = 0;
  BRACKETS.forEach((b) => {
    for (let i = 0; i < b.count; i++) {
      // Bracket biases — tweak sigMix a bit by bracket personality
      const r = rand();
      let signal;
      // Progressive consensus build-up across rounds
      const pressure = round === 1 ? 0.75 : round === 2 ? 0.95 : 1.15;
      const sellBias =
        b.value === 'doom_posters' ? 1.6 :
        b.value === 'policy_wonks' ? 0.9 :
        b.value === 'sovereigns' ? 0.5 :
        b.value === 'suits' ? 0.35 :
        b.value === 'insiders' ? 0.4 : 0.0;
      const buyBias =
        b.value === 'degens' ? 1.3 :
        b.value === 'agents' ? 0.4 :
        b.value === 'whales' ? 0.25 :
        b.value === 'macro' ? 0.15 : 0.0;
      const holdBias =
        b.value === 'whales' ? 0.5 :
        b.value === 'suits' ? 0.3 : 0.0;
      const p = {
        buy:  Math.max(0, sigMix.buy * pressure + buyBias),
        sell: Math.max(0, sigMix.sell * pressure + sellBias),
        hold: Math.max(0, sigMix.hold + holdBias)
      };
      const total = p.buy + p.sell + p.hold || 1;
      const norm = { buy: p.buy/total, sell: p.sell/total, hold: p.hold/total };
      if (r < norm.buy) signal = 'buy';
      else if (r < norm.buy + norm.sell) signal = 'sell';
      else signal = 'hold';

      const id = `${PREFIX[b.value]}-${String(i+1).padStart(2,'0')}`;
      const confidence = 0.4 + rand() * 0.6;
      agents.push({
        id, bracket: b.value, bracketDisplay: b.display,
        index: idx++, radius: b.radius, signal, confidence,
        flipped: round >= 2 && rand() < 0.18,
        prevSignal: null
      });
    }
  });
  return agents;
}

function bracketSummaries(agents) {
  return BRACKETS.map(b => {
    const slice = agents.filter(a => a.bracket === b.value);
    return {
      bracket: b.value,
      display_name: b.display,
      total: slice.length,
      buy_count:  slice.filter(a => a.signal === 'buy').length,
      sell_count: slice.filter(a => a.signal === 'sell').length,
      hold_count: slice.filter(a => a.signal === 'hold').length,
      avg_confidence: slice.reduce((s,a)=>s+a.confidence,0) / Math.max(1, slice.length),
    };
  });
}

const RATIONALES = [
  { agent: 'Q-03', bracket: 'Quants', signal: 'sell', round: 2,
    text: 'DCF re-rate assumes synergies that do not exist. Anthropic revenue ~$4.1B ARR; AAPL paying 120x. Pull-through narrative ignores existing OpenAI licensing leverage.',
    cites: ['U-07', 'I-04'] },
  { agent: 'D-14', bracket: 'Degens', signal: 'buy', round: 2,
    text: 'Flow is flow. Gap-and-go on unusual options volume in calls — $220 strikes printing. Chased it, staying long into rumor confirmation. FOMO factor extreme.',
    cites: [] },
  { agent: 'P-02', bracket: 'Policy Wonks', signal: 'sell', round: 2,
    text: 'FTC Lina Khan successor still hawkish on vertical AI integration. Deal is structurally un-approvable; expect 18 months of review and a forced divestiture remedy.',
    cites: ['X-01'] },
  { agent: 'W-04', bracket: 'Whales', signal: 'hold', round: 2,
    text: 'Decade horizon unchanged. Short-term volatility irrelevant — the Anthropic thesis is compute-bound, not rumor-bound. Watching for a pullback below $180 to add.',
    cites: [] },
  { agent: 'M-06', bracket: 'Macro', signal: 'sell', round: 2,
    text: 'Deal math only works in a 3% rate environment. Fed minutes next week could shift probability of 50bp cut, but balance-sheet unwind pressures large-cap M&A premium.',
    cites: ['S-02', 'U-05'] },
  { agent: 'S-02', bracket: 'Sovereigns', signal: 'sell', round: 2,
    text: 'Capital preservation mandate. EU sovereign wealth exposure through existing AAPL position already at policy cap — no desire to add concentration risk in an unresolved deal.',
    cites: [] },
  { agent: 'X-01', bracket: 'Doom-Posters', signal: 'sell', round: 2,
    text: 'Peak bubble. $500B for a company that still loses money on inference. History does not repeat but it absolutely rhymes — AOL/Time Warner, year 2000, same energy.',
    cites: [] },
  { agent: 'I-04', bracket: 'Insiders', signal: 'sell', round: 2,
    text: 'Anthropic\'s Claude API has existing TPU commitments to Google. Untangling the compute dependency alone is an 18-month engineering project. Integration story is fiction.',
    cites: ['Q-03'] },
  { agent: 'U-07', bracket: 'Suits', signal: 'hold', round: 2,
    text: 'Consensus view forming around regulatory skepticism. Maintaining pre-rumor allocation — waiting for official statement before repositioning institutional book.',
    cites: ['P-02', 'M-06'] },
  { agent: 'A-11', bracket: 'Agents', signal: 'buy', round: 2,
    text: 'Rule-set triggered on vol breakout + news-flow sentiment score > 0.72. Holding position per strategy mandate. No discretion; trigger was met.',
    cites: [] },
];

const HOLDINGS = [
  { ticker: 'AAPL',  shares: 1200, basis: 142.30, last: 218.40, sentiment: -0.48 },
  { ticker: 'MSFT',  shares: 380,  basis: 228.10, last: 410.75, sentiment: +0.12 },
  { ticker: 'NVDA',  shares: 550,  basis:  88.50, last: 142.20, sentiment: +0.31 },
  { ticker: 'GOOGL', shares: 410,  basis: 115.00, last: 165.90, sentiment: -0.22 },
  { ticker: 'META',  shares: 180,  basis: 298.40, last: 528.10, sentiment: +0.08 },
];

const REPLAY_CYCLES = [
  { id: 'c_2026_0418_a1', seed: 'Apple acquiring Anthropic for $500B',        when: '2026-04-18 09:42', dur: '4m 18s', consensus: 'SELL 58%' },
  { id: 'c_2026_0417_c2', seed: 'Saudi sovereign fund exits all US equities',  when: '2026-04-17 16:03', dur: '3m 52s', consensus: 'SELL 71%' },
  { id: 'c_2026_0416_b4', seed: 'Fed signals 50bp cut at May FOMC',            when: '2026-04-16 11:20', dur: '4m 02s', consensus: 'BUY 64%'  },
  { id: 'c_2026_0415_d0', seed: 'TSMC Arizona fab delayed 18 months',          when: '2026-04-15 08:14', dur: '3m 47s', consensus: 'SELL 53%' },
];

// ── v2: Live API activity ────────────────────────────────────────────
// Source catalog: what each data source is, color-coded group
const DATA_SOURCES = [
  { id: 'yfinance',   group: 'market',  label: 'yfinance',       desc: 'Yahoo Finance price/volume',     rate: '2000/hr',  latency: 145 },
  { id: 'polygon',    group: 'market',  label: 'polygon.io',     desc: 'Real-time trades + aggregates',  rate: '5/s',      latency:  52 },
  { id: 'fred',       group: 'macro',   label: 'FRED',           desc: 'St. Louis Fed economic series',  rate: '120/min',  latency: 210 },
  { id: 'edgar',      group: 'filings', label: 'SEC EDGAR',      desc: '10-K / 10-Q / 8-K filings',      rate: '10/s',     latency: 380 },
  { id: 'newsapi',    group: 'news',    label: 'NewsAPI',        desc: 'Headline aggregator',            rate: '500/day',  latency: 190 },
  { id: 'reuters',    group: 'news',    label: 'Reuters Conn.',  desc: 'Wire feed',                      rate: 'unlimited',latency:  90 },
  { id: 'reddit',     group: 'social',  label: 'reddit',         desc: '/r/wsb + /r/investing',          rate: '60/min',   latency: 240 },
  { id: 'x_api',      group: 'social',  label: 'x.com',          desc: 'Filtered cashtag stream',        rate: '300/15m',  latency: 170 },
  { id: 'fmp',        group: 'market',  label: 'FMP',            desc: 'Financial Modeling Prep',        rate: '300/min',  latency: 165 },
  { id: 'cryptopanic',group: 'news',    label: 'CryptoPanic',    desc: 'Crypto news + sentiment',        rate: '500/day',  latency: 220 },
];

const SOURCE_GROUP_COLOR = {
  market:  '#f5a524',  // amber
  macro:   '#8aa6ff',  // blue
  filings: '#b080ff',  // violet
  news:    '#5be7b8',  // mint
  social:  '#ff7aa8',  // pink
};

// Signal Wire events — mock stream of what agents are querying right now
// Each event: { t: offset-seconds, agent, source, query, result, used: bool }
const SIGNAL_WIRE_SEED = [
  { agent: 'Q-03', source: 'yfinance',    query: 'AAPL 1d OHLCV',          result: '$218.40  -0.82%',    used: true  },
  { agent: 'I-04', source: 'newsapi',     query: '"Anthropic" past 24h',   result: '12 hits',            used: true  },
  { agent: 'M-06', source: 'fred',        query: 'CPIAUCSL YoY',           result: '3.2%',               used: true  },
  { agent: 'D-11', source: 'reddit',      query: '/r/wsb top 25',          result: '8 mentions $AAPL',   used: false },
  { agent: 'U-02', source: 'edgar',       query: 'AAPL 10-K FY2025',       result: '14.2MB · cached',    used: true  },
  { agent: 'S-01', source: 'polygon',     query: 'SPY L1 book',            result: '578.40 × 12.4k',     used: true  },
  { agent: 'A-07', source: 'x_api',       query: 'cashtag:$AAPL',          result: '47 posts · -0.31',   used: true  },
  { agent: 'Q-08', source: 'fmp',         query: 'AAPL DCF inputs',        result: 'FCF yield 3.1%',     used: true  },
  { agent: 'M-02', source: 'fred',        query: 'DGS10',                  result: '4.28%',              used: true  },
  { agent: 'I-09', source: 'reuters',     query: 'topic:anthropic',        result: '3 wire items',       used: true  },
  { agent: 'X-02', source: 'cryptopanic', query: 'BTC sentiment 1h',       result: 'bear 0.61',          used: false },
  { agent: 'D-05', source: 'x_api',       query: 'cashtag:$NVDA',          result: '122 posts · +0.18',  used: true  },
  { agent: 'P-03', source: 'fred',        query: 'UNRATE',                 result: '3.9%',               used: true  },
  { agent: 'W-04', source: 'polygon',     query: 'AAPL dark pool',         result: '2.1M block',         used: true  },
  { agent: 'Q-05', source: 'yfinance',    query: 'MSFT 5d',                result: '$410.75  +0.31%',    used: false },
  { agent: 'U-07', source: 'edgar',       query: 'ANTH S-1 search',        result: '0 results',          used: false },
  { agent: 'A-03', source: 'newsapi',     query: 'acquisition rumor',      result: '4 hits',             used: true  },
  { agent: 'I-01', source: 'reuters',     query: 'topic:fed',              result: '7 wire items',       used: true  },
];

// Rolled-up per-source stats for the inspector modal
const SOURCE_STATS = [
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

window.AS_DATA = {
  BRACKETS, buildAgents, bracketSummaries,
  RATIONALES, HOLDINGS, REPLAY_CYCLES,
  DATA_SOURCES, SOURCE_GROUP_COLOR, SIGNAL_WIRE_SEED, SOURCE_STATS
};
