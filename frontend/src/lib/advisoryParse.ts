// src/lib/advisoryParse.ts
// Pure parsers + regex for AdvisoryV2 derive-or-stub strategy (D-08, D-09)
// AND ReportModal heading-gated subsection parsers (D-20, codex HIGH-4 +
// gemini #G1 — centralize section parsers out of inline ReportModal helpers).
//
// The portfolio_outlook field on backend AdvisoryReport (and report.content
// for ReportModal) is free markdown — there is no enforced section structure.
// These helpers are best-effort heuristic parsers; misses fall back to
// derived/stubbed values per KR-41.6-01 / KR-41.6-12.

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
    risk: /(?:^|\n)\s*\*?\*?(?:Risk|RISK)\*?\*?\s*[:\-]\s*([^\n]+)/i,
    upside: /(?:^|\n)\s*\*?\*?(?:Upside|UPSIDE|Opportunity)\*?\*?\s*[:\-]\s*([^\n]+)/i,
    rec: /(?:^|\n)\s*\*?\*?(?:Recommendation|REC|Action)\*?\*?\s*[:\-]\s*([^\n]+)/i,
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

// -- ReportModal section parsers (gemini #G1 centralize — moved out of inline
//    helpers in ReportModal.tsx to keep components clean and parsers testable) --
//
// Heading-gated policy (codex HIGH-4): each parser returns null/[] if the
// matching `## <Section>` H2 heading is ABSENT in the markdown. Callers
// omit the rich subsection entirely when the parser returns null/[] —
// NEVER synthesize from loose prose. This is the explicit conservative
// fallback both reviewers requested.

// Generic section extractor: returns the raw markdown body under a given
// H2 heading (case-insensitive heading match), or null if heading absent.
// Stops at the next H1/H2 or end-of-doc.
function extractSectionByHeading(md: string, headingText: string): string | null {
  if (!md || !headingText) return null;
  const escaped = headingText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(
    `(?:^|\\n)\\s*##\\s+${escaped}\\s*\\n([\\s\\S]+?)(?=\\n\\s*#{1,2}\\s+|$)`,
    'i',
  );
  const m = md.match(re);
  return m ? m[1].trim() : null;
}

export interface ConvergenceData {
  round: number;
  signal: string;
  weight: number;
}
export function parseConvergence(md: string): ConvergenceData[] | null {
  const section = extractSectionByHeading(md, 'Convergence');
  if (!section) return null;
  // Parse markdown table rows: "| 1 | BUY | 0.65 |" — bail if no table rows
  const rows: ConvergenceData[] = [];
  const rowRe = /^\|\s*(\d+)\s*\|\s*([A-Z]+)\s*\|\s*([\d.]+)\s*\|/gm;
  let m;
  while ((m = rowRe.exec(section)) !== null) {
    rows.push({ round: Number(m[1]), signal: m[2], weight: Number(m[3]) });
  }
  return rows.length > 0 ? rows : null;
}

export interface MomentEntry {
  round: number;
  description: string;
}
export function parseMoments(md: string): MomentEntry[] | null {
  const section =
    extractSectionByHeading(md, 'Moments') ||
    extractSectionByHeading(md, 'Key Moments');
  if (!section) return null;
  // Parse list items "- Round N: ..." or "- R1: ..."
  const out: MomentEntry[] = [];
  const itemRe = /^[-*]\s+(?:Round\s+|R)(\d+)\s*[:\-]\s*(.+)$/gim;
  let m;
  while ((m = itemRe.exec(section)) !== null) {
    out.push({ round: Number(m[1]), description: m[2].trim() });
  }
  return out.length > 0 ? out : null;
}

export interface InfluenceEntry {
  agentId: string;
  weight: number;
}
export function parseInfluences(md: string): InfluenceEntry[] | null {
  const section =
    extractSectionByHeading(md, 'Influence') ||
    extractSectionByHeading(md, 'Influence Leaders');
  if (!section) return null;
  const out: InfluenceEntry[] = [];
  // Match table rows OR list items: "| quants_03 | 0.42 |" or "- quants_03: 0.42"
  const rowRe = new RegExp(
    `(?:^\\|\\s*(${AGENT_ID_SRC})\\s*\\|\\s*([\\d.]+))|(?:^[-*]\\s+(${AGENT_ID_SRC})\\s*[:\\-]\\s*([\\d.]+))`,
    'gm',
  );
  // Dedup by agentId (keep the highest weight). The same agent can appear in
  // both a table and a bullet, which would otherwise yield duplicate React keys
  // in InfluenceChart and cause rows to be dropped/mis-reconciled (F-34).
  const byId = new Map<string, number>();
  let m;
  while ((m = rowRe.exec(section)) !== null) {
    const id = m[1] || m[3];
    const w = m[2] || m[4];
    if (id && w) {
      const weight = Number(w);
      const prev = byId.get(id);
      if (prev === undefined || weight > prev) byId.set(id, weight);
    }
  }
  for (const [agentId, weight] of byId) out.push({ agentId, weight });
  return out.length > 0 ? out : null;
}

export function parseDissent(md: string): string | null {
  // Dissent renders as raw markdown — return the section body or null.
  return extractSectionByHeading(md, 'Dissent');
}

export interface FollowupEntry {
  description: string;
}
export function parseFollowups(md: string): FollowupEntry[] | null {
  const section =
    extractSectionByHeading(md, 'Followups') ||
    extractSectionByHeading(md, 'Follow-ups') ||
    extractSectionByHeading(md, 'Next Steps');
  if (!section) return null;
  const out: FollowupEntry[] = [];
  const itemRe = /^[-*]\s+(.+)$/gm;
  let m;
  while ((m = itemRe.exec(section)) !== null) {
    out.push({ description: m[1].trim() });
  }
  return out.length > 0 ? out : null;
}
