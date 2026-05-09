// src/lib/markdown.ts — shared renderMarkdown helper.
// Lifted from frontend-react-archive/src/components/modals.jsx:40 (Phase 41.2 D-05).
// Used by AdvisoryV2 (Plan 03 W3 — D-09) and ReportModal rich rendering (Plan 03 W3 — D-20).
//
// Pattern preserved verbatim from the archive: marked.parse(..., { async: false })
// returns a string synchronously, then DOMPurify scrubs any XSS-prone HTML before
// the consumer drops it into a `dangerouslySetInnerHTML` container.
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export function renderMarkdown(source: string): string {
  if (!source) return '';
  const rawHtml = marked.parse(source, { async: false });
  return DOMPurify.sanitize(typeof rawHtml === 'string' ? rawHtml : '');
}
