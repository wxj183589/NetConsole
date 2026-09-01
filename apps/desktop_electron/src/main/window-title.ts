export interface ManagedWindowTitleTarget {
  setTitle(title: string): void
}

const titles = new WeakMap<object, string>()

export function setManagedWindowTitle(window: ManagedWindowTitleTarget, title: string): void {
  const normalized = String(title || '').trim() || 'NetConsole'
  titles.set(window, normalized)
  window.setTitle(normalized)
}

export function getManagedWindowTitle(window: object, fallback = 'NetConsole'): string {
  return titles.get(window) || fallback
}
