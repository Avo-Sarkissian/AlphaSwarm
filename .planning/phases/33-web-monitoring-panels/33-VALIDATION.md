---
phase: 33
slug: web-monitoring-panels
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest |
| **Config file** | frontend/vite.config.ts (vitest config inline) |
| **Quick run command** | `cd frontend && npm run type-check` |
| **Full suite command** | `cd frontend && npm run build && npm run type-check` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd frontend && npm run type-check`
- **After every plan wave:** Run `cd frontend && npm run build && npm run type-check`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 33-01-01 | 01 | 1 | WEB-03 | — | N/A | build | `cd frontend && npm run type-check` | ⬜ W0 | ⬜ pending |
| 33-01-02 | 01 | 1 | WEB-03 | — | N/A | build | `cd frontend && npm run type-check` | ⬜ W0 | ⬜ pending |
| 33-02-01 | 02 | 2 | WEB-04 | — | N/A | build | `cd frontend && npm run build` | ⬜ W0 | ⬜ pending |
| 33-02-02 | 02 | 2 | WEB-04 | — | N/A | build | `cd frontend && npm run build` | ⬜ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `frontend/src/components/RationaleFeed.vue` — stub component file
- [ ] `frontend/src/components/BracketPanel.vue` — stub component file
- [ ] Verify `d3-transition` installed: `cd frontend && npm ls d3-transition`

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Slide-in animation on new rationale entries | WEB-03 | Visual animation cannot be asserted via CLI | Open browser, trigger a WebSocket snapshot update, verify entries animate in |
| D3 bar width transition (600ms) | WEB-04 | CSS/SVG transitions are visual-only | Open browser, trigger round change, verify bars animate width smoothly |
| Feed capped at 20 entries, oldest fade out | WEB-03 | DOM count check requires browser | Open browser, send 25+ entries, verify only 20 rendered and oldest removed |
| Responsive layout alongside force graph | WEB-03, WEB-04 | Requires viewport resize | Resize browser window below 1024px, verify no clipping/overflow |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
