// @vitest-environment node
// Structural invariants for frontend/src. Every allow-list in this file may
// only shrink; when a list reaches zero entries, delete it and its exemption.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, posix, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../', import.meta.url));

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const FILES: readonly string[] = walk(SRC)
  .map((file) => relative(SRC, file).split(sep).join('/'))
  .sort();

const read = (file: string): string => readFileSync(join(SRC, file), 'utf8');
const isSource = (file: string): boolean => /\.(ts|tsx|css)$/.test(file) && !file.startsWith('__tests__/');
// Source text without comments, so prose such as "any bracket" never matches.
const code = (file: string): string =>
  read(file).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
const EXPLICIT_ANY = /:\s*any\b|\bas\s+any\b|<any>|\bany\[\]|\|\s*any\b|\bany\s*\|/;

const TSCONFIG = join(SRC, '..', 'tsconfig.app.json');
const stripJsonComments = (text: string): string =>
  text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const MAX_MODULE_LINES = 600;
const IMPORT_SPEC = /\b(?:from|import)\s*\(?\s*['"](\.{1,2}\/[^'"]+)['"]/g;

function importsOf(file: string): string[] {
  return [...read(file).matchAll(IMPORT_SPEC)].map((m) => posix.normalize(posix.join(posix.dirname(file), m[1] ?? '')));
}

// File names and mentions (v2.tsx, app_v2, interview_v2, components/v2),
// identifiers (InterviewV2, AdvisoryV2, ReportModalV2), class prefixes (rv2-,
// iv2-) and class suffixes (report-v2, ds-recent-row-v2).
const V2_NAME =
  /(^|\/)(app_|interview_)?v2\.tsx$|\bv2\.tsx\b|\b(rv2|iv2)-|\b[a-z]+(?:-[a-z]+)*-v2\b|\b[A-Z]\w*V2\b|app_v2|interview_v2|components\/v2\b/;

// Oversized components were an audit finding (the shell had 798 lines, the
// prototype feature file 1,343).
const LINE_CAPS: Readonly<Record<string, number>> = {
  'app/AppShell.tsx': 200,
  'features/dashboard/Dashboard.tsx': 350,
};

// Inline style objects in non-test .tsx files. Lower it when you convert
// more; never raise it.
const INLINE_STYLE_BUDGET = 151;
describe('frontend structure', () => {
  it('has no JavaScript sources', () => {
    expect(FILES.filter((file) => /\.jsx?$/.test(file))).toEqual([]);
  });

  it('has no prototype v2 file names, identifiers or class prefixes', () => {
    const offenders = FILES.filter((file) => isSource(file) && (V2_NAME.test(file) || V2_NAME.test(read(file))));
    expect(offenders).toEqual([]);
  });

  it('has no explicit any outside tests', () => {
    const offenders = FILES.filter((file) => /\.tsx?$/.test(file) && isSource(file) && EXPLICIT_ANY.test(code(file)));
    expect(offenders).toEqual([]);
  });

  it('keeps the shell and the dashboard small', () => {
    for (const [file, cap] of Object.entries(LINE_CAPS)) {
      expect(read(file).split('\n').length, file).toBeLessThanOrEqual(cap);
    }
  });

  it('stays within the inline-style budget', () => {
    const count = FILES.filter((file) => file.endsWith('.tsx') && isSource(file))
      .reduce((sum, file) => sum + (read(file).match(/style=\{\{/g)?.length ?? 0), 0);
    expect(count).toBeLessThanOrEqual(INLINE_STYLE_BUDGET);
  });

  it('compiles with the strict flags and without a JavaScript allowance', () => {
    const cfg = JSON.parse(stripJsonComments(readFileSync(TSCONFIG, 'utf8'))) as {
      compilerOptions: Record<string, unknown>;
      include: string[];
    };
    expect(cfg.compilerOptions['noUncheckedIndexedAccess']).toBe(true);
    expect(cfg.compilerOptions).not.toHaveProperty('allowJs');
    expect(cfg.compilerOptions).not.toHaveProperty('paths');
    expect(cfg.include.filter((glob) => glob.includes('.js'))).toEqual([]);
  });

  it('has no non-null assertion on an index access', () => {
    expect(FILES.filter((file) => /\.tsx?$/.test(file) && /\][!](?!=)/.test(code(file)))).toEqual([]);
  });

  it('keeps features independent of each other and of app/', () => {
    const offenders = FILES.filter((file) => file.startsWith('features/') && /\.tsx?$/.test(file)).flatMap((file) => {
      const feature = file.split('/')[1];
      return importsOf(file)
        .filter((target) => target.startsWith('app/') || (target.startsWith('features/') && target.split('/')[1] !== feature))
        .map((target) => `${file} -> ${target}`);
    });
    expect(offenders).toEqual([]);
  });

  it('keeps every app and feature module under the size cap', () => {
    const offenders = FILES.filter(
      (file) => /^(app|features)\/.*\.tsx?$/.test(file) && read(file).split('\n').length > MAX_MODULE_LINES,
    );
    expect(offenders).toEqual([]);
  });
});
