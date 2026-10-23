/** Fixed-capacity FIFO: pushing onto a full buffer drops the oldest item. */
export class RingBuffer<T> {
  private readonly items: (T | undefined)[];
  private start = 0;
  private length = 0;

  constructor(readonly capacity: number) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new RangeError(`RingBuffer capacity must be a positive integer, got ${capacity}`);
    }
    this.items = new Array<T | undefined>(capacity);
  }

  get size(): number {
    return this.length;
  }

  push(item: T): void {
    this.items[(this.start + this.length) % this.capacity] = item;
    if (this.length < this.capacity) this.length += 1;
    else this.start = (this.start + 1) % this.capacity;
  }

  toArray(): T[] {
    const out: T[] = [];
    for (let i = 0; i < this.length; i += 1) out.push(this.items[(this.start + i) % this.capacity] as T);
    return out;
  }
}
