# Phase 31: Vue SPA and Force-Directed Graph - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-13
**Phase:** 31-vue-spa-and-force-directed-graph
**Mode:** discuss
**Areas discussed:** Vue build + serving, Bracket clustering, Edge endpoint scope, Sidebar placement

## Locked Before Discussion (Prior Context)

From STATE.md accumulated decisions:
- SVG (not Canvas) for force graph at 100 nodes
- D3 as physics engine only, Vue owns SVG DOM — shallowRef + triggerRef, no Vue Proxy on D3 node array

## Gray Areas Presented

| Area | Options presented | User selected |
|------|------------------|---------------|
| Vue build + serving | Vite dev server + proxy / FastAPI-only (no HMR) | Vite dev server + proxy |
| Bracket clustering | Fixed centroids + D3 centering force / Free-running D3 | Fixed centroids + D3 centering force |
| Edge endpoint scope | Build in Phase 31 / Stub for Phase 31 real in Phase 32 | Build in Phase 31 |
| Sidebar placement | Fixed right panel / Floating overlay near node | Fixed right panel |

## Corrections Made

No corrections — user selected recommended option for all four areas.

## Decisions Captured

1. **Vue build + serving:** Vite on :5173 (HMR + proxy to :8000) in dev. `npm run build → dist/` served by FastAPI StaticFiles at `/` in production.
2. **Bracket clustering:** 10 centroids in a circle; D3 forceX/forceY pulls nodes toward their bracket centroid.
3. **Edge endpoint:** `GET /api/edges/{cycle_id}?round=N` built in Phase 31 (`routes/edges.py`). Phase 32 verifies but does not re-implement.
4. **Sidebar:** Fixed ~280px right panel. Graph container shrinks. Single agent at a time. Updates in real time from WebSocket stream.
