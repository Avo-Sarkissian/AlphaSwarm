// src/lib/advisoryParse.ts
// Pure parsers + regex for the AdvisoryV2 derive-or-stub strategy (D-08, D-09).
//
// The portfolio_outlook field on the backend AdvisoryReport is free markdown —
// there is no enforced section structure. These helpers are best-effort
// heuristic parsers; misses fall back to derived/stubbed values per KR-41.6-01.

// -- portfolio_outlook top-level parser (D-09) --
export interface ParsedOutlook {
  headline: string | null; // first H1/H2 heading text, or null
  summary: string; // full markdown body (rendered via renderMarkdown())
}

export function parseOutlook(md: string): ParsedOutlook {
  if (!md) return { headline: null, summary: '' };
  const headingMatch = md.match(/^\s*#{1,2}\s+(.+?)\s*$/m);
  const headline = headingMatch ? headingMatch[1].trim() : null;
  return { headline, summary: md };
}

// -- per-ticker section extraction (D-08 best-effort risk/upside/rec parser) --
// Looks for "## TICKER" or "### TICKER" then captures until the next H2/H3 or end-of-doc.
export function extractTickerSection(md: string, ticker: string): string | null {
  if (!md || !ticker) return null;
  // Escape ticker for regex (most tickers are A-Z, but be defensive)
  const escaped = ticker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(
    `(?:^|\\n)\\s*#{2,3}\\s+\\$?${escaped}\\b[^\\n]*\\n([\\s\\S]+?)(?=\\n\\s*#{2,3}\\s+|$)`,
    'i',
  );
  const m = md.match(re);
  return m ? m[1].trim() : null;
}

export type FieldLabel = 'risk' | 'upside' | 'rec';

export function extractField(section: string, label: FieldLabel): string | null {
  if (!section) return null;
  const labels: Record<FieldLabel, RegExp> = {
    risk: /(?:^|\n)\s*\*?\*?(?:Risk|RISK)\*?\*?\s*[:-]\s*([^\n]+)/i,
    upside: /(?:^|\n)\s*\*?\*?(?:Upside|UPSIDE|Opportunity)\*?\*?\s*[:-]\s*([^\n]+)/i,
    rec: /(?:^|\n)\s*\*?\*?(?:Recommendation|REC|Action)\*?\*?\s*[:-]\s*([^\n]+)/i,
  };
  const m = section.match(labels[label]);
  return m ? m[1].trim() : null;
}

// -- citation count regex (D-08 `agents` field; KR-41.6-10 documents this is a heuristic) --
// Real backend agent IDs are `{bracket}_{NN}` snake_case, e.g. quants_01,
// event_driven_05 — NOT the design-era `Q-03` prefix grammar.
const AGENT_ID_SRC =
  '(?:institutions|sell_side|event_driven|quants|degens|narrators|algos|macro|shorts|allocators)_\\d{2}';
export const AGENT_ID_RE = new RegExp(`\\b${AGENT_ID_SRC}\\b`, 'g');

export function countAgentCitations(text: string): number {
  if (!text) return 0;
  const matches = text.match(AGENT_ID_RE);
  if (!matches) return 0;
  return new Set(matches).size; // unique agents only
}

// gemini #G2 — strict intersection with live agent IDs from useAgents(). Closes
// KR-41.6-10 false-positive risk: regex over rationale_summary catches strings
// like "M-12" even when no agent with that ID exists in the live swarm. The
// intersection variant takes the regex hits AND keeps only IDs present in the
// current agents list.
//
// Usage in AdvisoryV2:
//   const { agents } = useAgents();
//   const liveIds = useMemo(() => new Set(agents.map(a => a.id)), [agents]);
//   const agentsCount = countAgentCitationsAgainst(item.rationale_summary, liveIds);
export function countAgentCitationsAgainst(
  text: string,
  liveIds: ReadonlySet<string>,
): number {
  if (!text) return 0;
  const matches = text.match(AGENT_ID_RE);
  if (!matches) return 0;
  const unique = new Set(matches);
  let count = 0;
  unique.forEach((id) => {
    if (liveIds.has(id)) count += 1;
  });
  return count;
}
