// @vitest-environment happy-dom
// renderMarkdown turns LLM-written markdown (reports, advisory) into HTML that is
// injected with dangerouslySetInnerHTML. These tests need a DOM: without a window,
// DOMPurify returns its input unchanged.
import { describe, expect, it } from 'vitest';
import { renderMarkdown } from '../../lib/markdown';

function mount(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host;
}

describe('renderMarkdown — rendering', () => {
  it('returns an empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('');
  });

  it('renders headings, emphasis and lists', () => {
    const host = mount(renderMarkdown('# Title\n\n**bold** and *it*\n\n- a\n- b'));
    expect(host.querySelector('h1')?.textContent).toBe('Title');
    expect(host.querySelector('strong')?.textContent).toBe('bold');
    expect(host.querySelectorAll('li')).toHaveLength(2);
  });

  it('keeps ordinary https links', () => {
    const host = mount(renderMarkdown('[docs](https://example.com/a)'));
    expect(host.querySelector('a')?.getAttribute('href')).toBe('https://example.com/a');
  });

  it('renders markdown tables', () => {
    const host = mount(renderMarkdown('| a | b |\n|:-:|--:|\n| 1 | 2 |'));
    expect(host.querySelectorAll('td')).toHaveLength(2);
  });
});

describe('renderMarkdown — dangerous markup is removed', () => {
  it.each([
    ['inline script tag', '<script>window.__xss = 1</script>hello'],
    ['img onerror', '<img src="x" onerror="window.__xss = 1">'],
    ['svg onload', '<svg onload="window.__xss = 1"><circle r="1"/></svg>'],
    ['iframe srcdoc', '<iframe srcdoc="<script>window.__xss=1</script>"></iframe>'],
    ['javascript: markdown link', '[click](javascript:window.__xss=1)'],
    ['javascript: html link', '<a href="javascript:window.__xss=1">x</a>'],
    ['data: html link', '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>'],
    ['event handler on div', '<div onclick="window.__xss=1">x</div>'],
    ['style tag', '<style>body{background:url(javascript:alert(1))}</style>'],
    ['form', '<form action="javascript:alert(1)"><button>go</button></form>'],
  ])('%s', (_label, source) => {
    const html = renderMarkdown(source);
    const host = mount(html);
    expect(host.querySelector('script, iframe, style, form, object, embed')).toBeNull();
    for (const el of Array.from(host.querySelectorAll('*'))) {
      for (const attr of Array.from(el.attributes)) {
        expect(attr.name.startsWith('on')).toBe(false);
        expect(attr.value.toLowerCase()).not.toMatch(/^\s*(javascript|data|vbscript):/);
      }
    }
    expect(html.toLowerCase()).not.toContain('javascript:');
  });

  it('drops inline style attributes so output cannot cover the dashboard', () => {
    const host = mount(renderMarkdown('<div style="position:fixed;inset:0">cover</div>'));
    expect(host.querySelector('[style]')).toBeNull();
    expect(host.textContent).toContain('cover');
  });
});
