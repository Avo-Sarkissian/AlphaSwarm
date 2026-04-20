// DEV-ONLY fixture used by tweaks.jsx to preview the holdings modal during development.
// Plan 04 swaps production holdings to /api/holdings. This file MUST NOT be statically
// imported anywhere on the live render path outside an `import.meta.env.DEV` block.

export interface Holding {
  ticker: string;
  shares: number;
  basis: number;
  last: number;
  sentiment: number;
}

export const HOLDINGS: ReadonlyArray<Holding> = [
  { ticker: 'AAPL',  shares: 1200, basis: 142.30, last: 218.40, sentiment: -0.48 },
  { ticker: 'MSFT',  shares: 380,  basis: 228.10, last: 410.75, sentiment: +0.12 },
  { ticker: 'NVDA',  shares: 550,  basis:  88.50, last: 142.20, sentiment: +0.31 },
  { ticker: 'GOOGL', shares: 410,  basis: 115.00, last: 165.90, sentiment: -0.22 },
  { ticker: 'META',  shares: 180,  basis: 298.40, last: 528.10, sentiment: +0.08 },
];
