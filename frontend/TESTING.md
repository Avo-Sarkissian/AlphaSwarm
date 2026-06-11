# CI & frontend tests

- Run locally: `npm test` (or `npx vitest run`) from `frontend/`; type check with `npm run check`.
- Tests live in `src/__tests__/` and are pure-function only (no jsdom, no component rendering).
- They guard the WS **wire contract**: `adaptSnapshot()` against the exact backend snapshot shape (`dataclasses.asdict(StateSnapshot)` from `src/alphaswarm/state.py` via `web/broadcaster.py`), v2 bracket/agent-ID mapping, `AGENT_ID_RE` citation grammar, and `BRACKETS` composition (counts sum to 100).
- If the backend snapshot shape changes, update the canned snapshot in `src/__tests__/frame.test.ts` in the same PR.
- CI runs both suites on push/PR to `master` via `.github/workflows/ci.yml` (backend: uv + pytest; frontend: tsc, vitest, vite build).
