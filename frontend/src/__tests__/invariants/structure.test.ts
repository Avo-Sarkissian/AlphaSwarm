// @vitest-environment node
// Structural invariants for frontend/src. Every allow-list in this file may
// only shrink; when a list reaches zero entries, delete it and its exemption.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
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

// File names and mentions (v2.tsx, app_v2, interview_v2, components/v2),
// identifiers (InterviewV2, AdvisoryV2, ReportModalV2), class prefixes (rv2-,
// iv2-) and class suffixes (report-v2, ds-recent-row-v2).
const V2_NAME =
  /(^|\/)(app_|interview_)?v2\.tsx$|\bv2\.tsx\b|\b(rv2|iv2)-|\b[a-z]+(?:-[a-z]+)*-v2\b|\b[A-Z]\w*V2\b|app_v2|interview_v2|components\/v2\b/;

describe('frontend structure', () => {
  it('has no JavaScript sources', () => {
    expect(FILES.filter((file) => /\.jsx?$/.test(file))).toEqual([]);
  });

  it('has no prototype v2 file names, identifiers or class prefixes', () => {
    const offenders = FILES.filter((file) => isSource(file) && (V2_NAME.test(file) || V2_NAME.test(read(file))));
    expect(offenders).toEqual([]);
  });
});
