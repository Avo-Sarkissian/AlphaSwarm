// src/lib/advisoryParse.ts
// Pure parsers + regex for the advisory panel: the outlook headline (D-09) and
// the agent-citation count. Per-item risk/upside/stats come from the backend
// (see lib/advisoryView.ts), never from the outlook prose.

// -- portfolio_outlook top-level parser (D-09) --
export interface ParsedOutlook {
  headline: string | null; // first H1/H2 heading text, or null
  summary: string; // full markdown body (rendered via renderMarkdown())
}

export function parseOutlook(md: string): ParsedOutlook {
  if (!md) return { headline: null, summary: '' };
  const headingMatch = md.match(/^\s*#{1,2}\s+(.+?)\s*$/m);
  const headline = headingMatch?.[1]?.trim() ?? null;
  return { headline, summary: md };
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
// Usage in the advisory panel:
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
