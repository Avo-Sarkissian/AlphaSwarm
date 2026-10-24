// src/lib/advisoryParse.ts
// Pure parser for the advisory panel: the outlook headline (docs/DECISIONS.md#p41-6-d-09). Per-item
// risk/upside/stats and swarm evidence come from the backend (see
// lib/advisoryView.ts), never from the outlook prose.

// -- portfolio_outlook top-level parser (docs/DECISIONS.md#p41-6-d-09) --
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
