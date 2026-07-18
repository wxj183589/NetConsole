// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

import { applyNetConsoleTheme, resolveTheme, stopThemeSynchronization } from './theme'

function installMatchMedia(initial: boolean) {
  let listener: ((event: MediaQueryListEvent) => void) | undefined
  const query = {
    matches: initial,
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn((_name: string, callback: (event: MediaQueryListEvent) => void) => { listener = callback }),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList
  vi.spyOn(window, 'matchMedia').mockReturnValue(query)
  return { query, emit: (matches: boolean) => listener?.({ matches } as MediaQueryListEvent) }
}

afterEach(() => {
  stopThemeSynchronization()
  vi.restoreAllMocks()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.style.removeProperty('--nc-primary')
  document.documentElement.style.removeProperty('--nc-accent')
})

describe('NetConsole theme runtime', () => {
  it('resolves explicit and system themes', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
    expect(resolveTheme('auto', true)).toBe('dark')
  })

  it('applies the semantic theme and configured primary color', () => {
    installMatchMedia(false)
    expect(applyNetConsoleTheme('dark', '#2563EB')).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.style.getPropertyValue('--nc-primary')).toBe('#2563EB')
  })

  it('tracks operating-system changes only while auto theme is active', () => {
    const media = installMatchMedia(false)
    applyNetConsoleTheme('auto', '#0078D4')
    expect(document.documentElement.dataset.theme).toBe('light')

    media.emit(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    applyNetConsoleTheme('light', '#0078D4')
    expect(media.query.removeEventListener).toHaveBeenCalled()
  })
})
