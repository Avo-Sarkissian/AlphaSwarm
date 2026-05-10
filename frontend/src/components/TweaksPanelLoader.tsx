import React, { Suspense } from 'react';
import type { ComponentType } from 'react';

// Dev-only mount gate around TweaksPanel.
//
// Lifted from frontend-react-archive/src/components/TweaksPanelLoader.tsx
// (W2 Plan 41.6-02 task 2). In production, Vite resolves
// `import.meta.env.DEV` to `false` at compile time and esbuild/Rollup dead-
// code elimination removes the `import('./tweaks')` branch entirely — the
// resulting chunk never emits TweaksPanel code into `dist/assets/*.js`. The
// belt-and-braces `if (!import.meta.env.DEV) return null` below prevents any
// accidental mount even if a stray caller survives.
//
// Acceptance proof: `grep -rF TweaksPanel frontend/dist/assets/` must be
// empty after `npm run build` (W2 task 4 build gate).

export interface TweaksPanelLoaderProps {
  state: unknown;
  setState: unknown;
  onClose: () => void;
}

const LazyTweaks = React.lazy<ComponentType<TweaksPanelLoaderProps>>(() =>
  import.meta.env.DEV
    ? import('./tweaks').then((m) => ({
        default: m.TweaksPanel as unknown as ComponentType<TweaksPanelLoaderProps>,
      }))
    : Promise.resolve({
        default: (() => null) as unknown as ComponentType<TweaksPanelLoaderProps>,
      }),
);

export function TweaksPanelLoader(props: TweaksPanelLoaderProps) {
  if (!import.meta.env.DEV) return null;
  return (
    <Suspense fallback={null}>
      <LazyTweaks {...props} />
    </Suspense>
  );
}
