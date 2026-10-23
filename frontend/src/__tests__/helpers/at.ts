// Test helper: the element at `index`, failing the test when it is missing.
// Replaces `xs[i]!` now that noUncheckedIndexedAccess types `xs[i]` as T | undefined.
export function at<T>(items: ArrayLike<T>, index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`expected an element at index ${index} of ${items.length}`);
  return item;
}
