# Frontend tests and lint

Run from `frontend/`:

| Command | What it checks |
|---|---|
| `npx tsc -b --noEmit` | Types, including the tests and the compile-time wire key lists |
| `npx vitest run` | Unit, hook and component tests |
| `npm run lint` | ESLint: typescript-eslint and react-hooks are errors; jsx-a11y rules are warnings until the accessibility pass |
| `npm run build` | `tsc -b` plus the production bundle |

The CI `frontend` job runs `npm ci`, `npm audit --omit=dev --audit-level=high`, `npm run lint`,
`npx vitest run` and `npm run build` (which runs `tsc -b`) on Node 22 (`frontend/.nvmrc`).

## Layout

| Folder | Contents | Environment |
|---|---|---|
| `src/__tests__/lib/` | Helpers from `src/lib/` | node; happy-dom when the helper needs a DOM (`markdown.test.ts`: DOMPurify) |
| `src/__tests__/hooks/` | Hooks through `renderHook` | happy-dom |
| `src/__tests__/components/` | Components through React Testing Library and `renderWithFrame` | happy-dom |
| `src/__tests__/helpers/` | `renderWithFrame`, `FakeWebSocket`, `wireKeys` | — |
| `src/__tests__/fixtures/` | Golden frames written by the backend; never edit by hand | — |
| `src/__tests__/*.test.ts` | Adapter, data and parser tests | node |

`src/__tests__/setup.ts` unmounts React Testing Library renders after each test.

## Rules

1. Test production code. Import from `src/lib/`, `src/hooks/`, `src/adapter/` or `src/context/`;
   never copy logic into a test file. When a component holds logic worth testing, move it into
   `src/lib/` first.
2. Hook and component tests, and any test of code that needs a DOM, start with
   `// @vitest-environment happy-dom`; pure tests stay in node.
3. Use fake timers for anything time-based (`vi.useFakeTimers()`, `vi.advanceTimersByTime()`).
4. `renderWithFrame(ui, { raw?, frame? })` renders inside the production provider stack
   (`FrameProviders`), starting from `fixtures/ws_snapshot.json`.
5. Under happy-dom, DOMPurify stops at the first element it removes (happy-dom's NodeIterator
   skips the DOM's removal steps; browsers continue). Give each sanitizer case in
   `markdown.test.ts` at most one element to remove; the `it.fails` test there flags the day
   happy-dom fixes this. happy-dom's `Node.prototype.nodeName` getter also returns `''` for
   elements (browsers return the tag name), and DOMPurify reads that getter, so
   `markdown.test.ts` patches it in a `vi.hoisted` block before DOMPurify loads; a test there
   fails once the patch is no longer needed.

## Wire contract

- The backend's `alphaswarm.web.wire.StateFrame` is mirrored by `WireStateFrame` in `src/types.ts`;
  `adapter/frame.ts` maps it to the camelCase `StateFrame` view.
- `tests/test_wire_contract.py` writes `ws_snapshot.json` (live, mid round 2), `ws_snapshot_replay.json`,
  `ws_snapshot_failed.json` (a run that failed in round 2, so `last_error` is set) and `brackets.json`
  from a deterministic StateStore.
- `frame.test.ts` compares the fixture keys with `helpers/wireKeys.ts`, and `tsc` checks those lists
  against `src/types.ts`, so a field added, renamed or removed on either side fails.
  `data.test.ts` checks `BRACKETS` against `brackets.json`.
- To change the frame: edit `web/wire.py` and its mapper, run
  `UPDATE_GOLDEN=1 uv run pytest -q tests/test_wire_contract.py && (cd frontend && npx vitest run)`,
  update `types.ts`, `wireKeys.ts` and the adapter, and explain the fixture diff in the commit body.
- Adding a field keeps `schema_version` 1. Renaming, removing or changing the meaning of a field bumps
  `SCHEMA_VERSION` in `web/wire.py` and `SUPPORTED_SCHEMA_VERSION` in `adapter/frame.ts` together.

## Lint baseline

The first lint run (October 2026) had 0 errors and 94 warnings: 72 jsx-a11y, 13 `no-explicit-any`
in `components/app_v2.tsx`, 7 `react-hooks/set-state-in-effect`, 2 `react-hooks/refs`. New code
should add none. The shell's `no-explicit-any` override is gone: the rule is an error everywhere.

## Dead-code and placebo gates

- `npm run knip` fails on unused files, exports and dependencies (`knip.json`). `d3-scale` is ignored until the graph redesign imports it.
- ESLint rejects any `<button>` without `onClick` or `type="submit"`: delete a placebo control instead of disabling it.
- `src/__tests__/helpers/fetchStub.ts`: `stubFetch(routes)` answers `fetch` from a route table matched on the full URL including the query (unmatched requests get a 404 envelope) and returns the mock, so `requestedUrls(mock)` can assert encoded query strings; `ensureResizeObserver()` for components that render the SVG graph.
- `src/__tests__/helpers/fetchRoutes.ts`: `stubFetchRoutes(routes)` routes on method and path only (the query is ignored), and a handler can answer by call count; it stays for the tests already written against it.
- `src/__tests__/helpers/renderShell.tsx`: `renderShell(ui, opts)` is `renderWithFrame` plus the real `EdgesProvider`; use it for the dashboard, the interview takeover and the bracket deep dive, which read `useEdgesCtx()`.
- The frame watchdog is tested with the shared `FakeWebSocket` helper and fake timers (`hooks/useWebSocket.watchdog.test.tsx`).
- Pure logic lives in `src/lib/` and is tested in node; component tests use `// @vitest-environment happy-dom` and `renderWithFrame`.

## Structure invariants

`src/__tests__/invariants/structure.test.ts` (node environment) reads the source tree and
fails on: any `.js`/`.jsx` under `src/`, prototype `v2` names, explicit `any` outside
tests, `]!` non-null assertions (tests use `at()` from `helpers/at.ts` or `?.` inside the
assertion instead), a tsconfig without `noUncheckedIndexedAccess` (or with
`allowJs`/`paths`), a feature importing another feature or `app/`, an `app/`/`features/`
module over 600 lines, planning-process tags in `app/`/`features/` comments, and more
inline `style={{…}}` objects than `INLINE_STYLE_BUDGET`. Lower the budget when you remove
inline styles; never raise it.

Component tests for the shell stub heavy children by module path (`vi.mock('../../features/…')`);
`ModalHost.test.tsx` and `AppShellModals.test.tsx` are the reference for overlay behaviour.
