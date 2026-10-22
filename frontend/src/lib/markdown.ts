// src/lib/markdown.ts — shared renderMarkdown helper.
// Lifted from frontend-react-archive/src/components/modals.jsx:40 (Phase 41.2 D-05).
// Used by AdvisoryV2 (Plan 03 W3 — D-09) and ReportModal rich rendering (Plan 03 W3 — D-20).
//
// Pattern preserved verbatim from the archive: marked.parse(..., { async: false })
// returns a string synchronously, then DOMPurify scrubs any XSS-prone HTML before
// the consumer drops it into a `dangerouslySetInnerHTML` container.
import { marked } from 'marked';
import DOMPurify from 'dompurify';

// The markdown is written by an LLM. DOMPurify's defaults already strip script
// vectors; also forbid <style>, <form> and inline style attributes so model output
// can neither restyle the dashboard nor render a convincing fake form.
const SANITIZE_CONFIG = {
  FORBID_TAGS: ['style', 'form'],
  FORBID_ATTR: ['style'],
};

export function renderMarkdown(source: string): string {
  if (!source) return '';
  const rawHtml = marked.parse(source, { async: false });
  return DOMPurify.sanitize(typeof rawHtml === 'string' ? rawHtml : '', SANITIZE_CONFIG);
}
