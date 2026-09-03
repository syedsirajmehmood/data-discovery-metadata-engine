import '@testing-library/jest-dom/vitest'

/**
 * Node ships an experimental built-in `localStorage` global (backed by
 * --localstorage-file, unset here) that shadows jsdom's real
 * implementation and lacks working methods (e.g. `.clear`). vitest's
 * jsdom environment doesn't override it because jsdom exposes
 * `localStorage` via a prototype accessor, not an own property, so it
 * never enters vitest's window->global key-copy list. Replace it with a
 * simple in-memory Storage so src/lib/recentlyViewed.ts (and its tests)
 * behave the same here as in a real browser.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>()

  get length(): number {
    return this.store.size
  }

  clear(): void {
    this.store.clear()
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null
  }

  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

Object.defineProperty(globalThis, 'localStorage', {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
})
