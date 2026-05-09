import React, { Suspense } from 'react';
import type { ComponentType } from 'react';

// Dynamic-import wrapper for the dev-only TweaksPanel.
//
// In production, Vite resolves `import.meta.env.DEV` to `false` at compile time
// and the esbuild/Rollup dead-code elimination removes the `import('./tweaks')`
// branch entirely — the resulting chunk never emits TweaksPanel code into
// `dist/assets/*.js`. The belt-and-braces `if (!import.meta.env.DEV) return null`
// below prevents any accidental mount even if a stray caller survives.
//
// Reviewer item 19 proof: `grep -rF TweaksPanel dist/assets/` must be empty
// after `npm run build`.

export interface TweaksPanelLoaderProps {
  state: unknown;
  setState: unknown;
  onClose: () => void;
}

// Cast the lazy-loaded module default to a generic ComponentType so the two
// branches (real panel in DEV, null-renderer in prod) share one signature.
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
