// src/lib/markdown.ts — shared renderMarkdown helper.
// Lifted from frontend-react-archive/src/components/modals.jsx:40 (Phase 41.2 D-05).
// Used by AdvisoryV2 (Plan 03 W3 — D-09) and ReportModal rich rendering (Plan 03 W3 — D-20).
//
// Pattern preserved verbatim from the archive: marked.parse(..., { async: false })
// returns a string synchronously, then DOMPurify scrubs any XSS-prone HTML before
// the consumer drops it into a `dangerouslySetInnerHTML` container.
import { marked } from 'marked';
import DOMPurify, { type Config } from 'dompurify';

// The markdown is written by an LLM, and the advisory outlook is written with the
// holdings in its prompt. Keep only what marked emits for ordinary markdown:
// - no class, id, style, data or aria attributes, so the output can neither reuse
//   nor override the app's CSS (it cannot cover the dashboard);
// - no form controls, so it cannot render a fake prompt (GFM task-list checkboxes
//   go too);
// - no images or other media, so opening a report or advisory loads nothing; links
//   stay, and only a click follows them.
const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
    'strong', 'em', 'del', 'code', 'pre', 'blockquote', 'a',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
  ],
  ALLOWED_ATTR: ['href', 'title', 'align', 'start'],
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
} satisfies Config;

export function renderMarkdown(source: string): string {
  if (!source) return '';
  const rawHtml = marked.parse(source, { async: false });
  return DOMPurify.sanitize(typeof rawHtml === 'string' ? rawHtml : '', SANITIZE_CONFIG);
}
