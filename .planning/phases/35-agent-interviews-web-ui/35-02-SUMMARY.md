---
phase: 35-agent-interviews-web-ui
plan: "02"
subsystem: web-ui
tags: [vue, typescript, interview, frontend, spa]
dependency_graph:
  requires:
    - frontend/src/App.vue (selectedAgentId, sidebarOpen, isIdle, Transition block)
    - frontend/src/components/AgentSidebar.vue (close emit, snapshot inject)
    - frontend/src/types.ts (StateSnapshot.phase)
    - frontend/src/assets/variables.css (design tokens)
    - POST /api/interview/{agent_id} (Plan 01 backend endpoint)
  provides:
    - frontend/src/components/InterviewPanel.vue (multi-turn chat panel)
    - AgentSidebar "Interview Agent NN" button (phase-gated to 'complete')
    - App.vue interviewAgentId ref + mutual exclusion wiring
    - isIdle BLOCKER fix (ForceGraph visible in 'complete' phase)
  affects:
    - frontend/src/App.vue (isIdle, sidebarOpen, onSelectAgent, new handlers, template)
    - frontend/src/components/AgentSidebar.vue (new emit, isComplete, interview button + CSS)
tech_stack:
  added: []
  patterns:
    - Module-level reactive(new Map()) for cross-mount conversation persistence (D-05)
    - Bidirectional mutual exclusion via interviewAgentId ref (D-04)
    - Optimistic UI: user message appended before fetch resolves
    - encodeURIComponent for safe agent_id URL construction
    - Two separate Transition blocks for panel switching (avoids single-root constraint)
    - Phase gating: interview button visible only when snapshot.phase === 'complete'
key_files:
  created:
    - frontend/src/components/InterviewPanel.vue
  modified:
    - frontend/src/components/AgentSidebar.vue
    - frontend/src/App.vue
decisions:
  - "Two separate Transition blocks (not v-if/v-else in one block) chosen to satisfy Vue single-root-child constraint cleanly"
  - "Module-level reactive(new Map()) over component-local Map — persists conversation history across panel close/reopen without prop-drilling or provide/inject"
  - "isIdle narrowed to phase === 'idle' only — 'complete' was incorrectly included (CONFIRMED BLOCKER), hiding ForceGraph when Interview flow must be accessible"
  - "sidebar__interview-divider added as a separate HR (not reusing sidebar__divider) to avoid style bleed from the existing divider rule"
metrics:
  duration: "8 minutes"
  completed_date: "2026-04-15"
  tasks_completed: 2
  files_changed: 3
---

# Phase 35 Plan 02: Interview Frontend Panel Summary

**One-liner:** Vue 3 InterviewPanel SFC with reactive(new Map) conversation store, AgentSidebar interview button gated to 'complete' phase, App.vue mutual exclusion wiring, and isIdle BLOCKER fix restoring ForceGraph visibility in 'complete' phase.

## What Was Built

### InterviewPanel.vue (new, 286 lines)

A new `frontend/src/components/InterviewPanel.vue` SFC providing:

- **Dual script blocks**: `<script lang="ts">` at module level declares the `reactive(new Map())` conversation store (survives component unmount/remount per D-05); `<script setup lang="ts">` contains component logic
- **Conversation persistence**: `allConversations: Map<string, ChatMessage[]>` keyed by `agent_id` — reopening the same agent resumes the prior conversation
- **Fetch with safety**: `POST /api/interview/${encodeURIComponent(props.agentId)}` handles 404/409/422/503 with distinct inline error messages
- **Optimistic UI**: user message appended to history before fetch resolves
- **Thinking indicator**: `.interview-panel__thinking` with `@keyframes thinking-pulse` animation (0.4 → 1.0 → 0.4 opacity over 1.5s)
- **Auto-scroll**: `nextTick(() => chatContainer.scrollTop = scrollHeight)` after each message append
- **No unused imports**: `noUnusedLocals` compliant — only `{ ref, computed, nextTick }` in setup, `{ reactive }` in module block

### AgentSidebar.vue (modified)

- Added `(e: 'open-interview', agentId: string): void` to `defineEmits`
- Added `isComplete` computed: `snapshot.value.phase === 'complete'`
- Added `<template v-if="isComplete">` block at bottom of sidebar: `<hr class="sidebar__interview-divider" />` + `<button class="sidebar__interview-btn">Interview {{ agentName }}</button>`
- Added `.sidebar__interview-divider` and `.sidebar__interview-btn` / `.sidebar__interview-btn:hover` CSS rules

### App.vue (modified — CONFIRMED BLOCKER FIXED)

- `import InterviewPanel from './components/InterviewPanel.vue'`
- `const interviewAgentId = ref<string | null>(null)`
- **BLOCKER FIX**: `isIdle` changed from `phase === 'idle' || phase === 'complete'` to `phase === 'idle'` — ForceGraph is now visible in 'complete' phase
- `onSelectAgent` now clears `interviewAgentId.value = null` before setting `selectedAgentId` (D-04 bidirectional mutual exclusion)
- `onOpenInterview(agentId)`: sets `interviewAgentId`, clears `selectedAgentId`
- `onCloseInterview()`: clears `interviewAgentId`
- `sidebarOpen` extended: `selectedAgentId.value !== null || interviewAgentId.value !== null` (graph/panel-strip shrink for either panel)
- Template: two separate `<Transition name="sidebar">` blocks — one for `InterviewPanel` (`v-if="interviewAgentId"`), one for `AgentSidebar` (`v-if="selectedAgentId && !interviewAgentId"`)

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create InterviewPanel.vue with reactive Map store and encoded fetch URL | b698c70 | frontend/src/components/InterviewPanel.vue |
| 2 | AgentSidebar interview button, App.vue panel wiring, and isIdle BLOCKER fix | 67e0a47 | frontend/src/components/AgentSidebar.vue, frontend/src/App.vue |

## Verification

All plan verification checks pass:

1. `cd frontend && npx vue-tsc --noEmit` — exits 0 (no errors, noUnusedLocals enforced)
2. `grep -n "isIdle" frontend/src/App.vue` — line 49: `snapshot.value.phase === 'idle'` (no `'complete'`)
3. `grep -n -A3 "function onSelectAgent" frontend/src/App.vue` — shows `interviewAgentId.value = null` on line 28
4. `grep "open-interview" frontend/src/components/AgentSidebar.vue` — emit declared and used
5. `grep "interviewAgentId" frontend/src/App.vue` — ref, sidebarOpen, onOpenInterview, onCloseInterview, template v-if all reference it
6. `grep "InterviewPanel" frontend/src/App.vue` — import on line 6 and template usage on line 90
7. `grep "reactive.*new Map" frontend/src/components/InterviewPanel.vue` — confirmed
8. `grep "encodeURIComponent" frontend/src/components/InterviewPanel.vue` — confirmed in fetch URL
9. `grep -E "^import.*watch|^import.*PropType" frontend/src/components/InterviewPanel.vue` — returns zero matches
10. `grep "api/interview" frontend/src/components/InterviewPanel.vue` — confirmed in fetch call

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing CSS] Added `sidebar__interview-divider` as a separate class**
- **Found during:** Task 2
- **Issue:** Plan specified `.sidebar__divider` for the new divider before the interview button, but that class name already exists in AgentSidebar with its own margin/style rules. Reusing it would share style declarations and could create confusion in future modifications.
- **Fix:** Added `.sidebar__interview-divider` as a distinct class with the same visual output (`border-top: 1px solid var(--color-border)`) — avoids potential style bleed from the existing divider rule.
- **Files modified:** `frontend/src/components/AgentSidebar.vue`
- **Commit:** 67e0a47

No other deviations — plan executed as specified.

## Known Stubs

None — all components are fully wired. InterviewPanel connects to the live Plan 01 backend endpoint. AgentSidebar button emits to App.vue which renders the panel. The reactive Map conversation store is populated by actual fetch responses. No hardcoded data, placeholder text, or mock responses.

## Self-Check: PASSED

Files exist:
- [x] `frontend/src/components/InterviewPanel.vue` — FOUND (286 lines)
- [x] `frontend/src/components/AgentSidebar.vue` — FOUND (modified, 164 lines)
- [x] `frontend/src/App.vue` — FOUND (modified, 246 lines)

Commits exist:
- [x] `b698c70` — FOUND (InterviewPanel.vue creation)
- [x] `67e0a47` — FOUND (AgentSidebar + App.vue wiring)
