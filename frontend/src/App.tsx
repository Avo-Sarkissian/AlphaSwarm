// WAVE-1-NOTE: AppShell body stays the Wave-0 placeholder until Plan 02 Task 2
// rewrites this file with the 6-context provider tree. The only Task 1.5
// change here is the DEV-only `_smoke` side-effect import at the top — this
// forces Vite + tsc to compile every ported JSX component that would otherwise
// be tree-shaken out (reviewer item 13).
if (import.meta.env.DEV) {
  // Side-effect import: eagerly pulls every ported JSX component through the
  // smoke harness so tsc + Vite type-check + bundle them even though the
  // AppShell does not mount them yet.
  void import('./_smoke');
}

export function App() {
  return (
    <div
      style={{
        padding: 24,
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <h1>AlphaSwarm — Wave 1 scaffold</h1>
      <p>
        Ported components compiled via <code>_smoke.tsx</code> harness. Plan 02 Task 2 replaces
        this placeholder with the 6-context provider tree + mounted AppShell.
      </p>
    </div>
  );
}
