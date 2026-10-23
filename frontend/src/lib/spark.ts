/** Bar heights in px, scaled to the window maximum; zero or invalid samples draw minPx. */
export function sparkBars(samples: readonly number[], maxPx = 16, minPx = 2): number[] {
  const values = samples.map((v) => (Number.isFinite(v) && v > 0 ? v : 0));
  const top = Math.max(0, ...values);
  if (top === 0) return values.map(() => minPx);
  return values.map((v) => Math.round(minPx + (v / top) * (maxPx - minPx)));
}
