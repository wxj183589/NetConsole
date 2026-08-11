// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { applyNetConsoleTheme, resolveTheme, stopThemeSynchronization } from './theme'

const readThemeCss = (name: string) => readFileSync(
  fileURLToPath(new URL(name, import.meta.url)),
  'utf8',
)
const darkCss = readThemeCss('./dark.css')
const elementPlusCss = readThemeCss('./element-plus.css')
const lightCss = readThemeCss('./light.css')

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
  Reflect.deleteProperty(window, 'netconsoleDesktop')
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
    const reportRendererReady = vi.fn()
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { reportRendererReady },
    })
    applyNetConsoleTheme('auto', '#0078D4')
    expect(document.documentElement.dataset.theme).toBe('light')

    media.emit(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(reportRendererReady).toHaveBeenLastCalledWith({ resolvedTheme: 'dark' })

    applyNetConsoleTheme('light', '#0078D4')
    expect(media.query.removeEventListener).toHaveBeenCalled()
  })

  it('reports only the resolved theme through the minimal desktop bridge', () => {
    const reportRendererReady = vi.fn()
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { reportRendererReady },
    })
    installMatchMedia(false)

    applyNetConsoleTheme('dark', '#0078D4')

    expect(reportRendererReady).toHaveBeenCalledWith({ resolvedTheme: 'dark' })
  })

  it('defines complete light and dark shell tokens with compatibility aliases', () => {
    expect(lightCss).toContain('--nc-bg-app: #f4f6f8')
    expect(lightCss).toContain('--nc-bg-sidebar: #ffffff')
    expect(lightCss).toContain('--nc-bg-page: var(--nc-bg-app)')
    expect(lightCss).toContain('--nc-bg-card: var(--nc-bg-panel)')
    expect(lightCss).not.toContain('--nc-bg-sidebar: #0b1220')
    expect(darkCss).toContain('--nc-bg-app: #0f141c')
    expect(darkCss).toContain('--nc-bg-sidebar: #121923')
    expect(darkCss).toContain('--nc-bg-panel: #18212d')
    expect(darkCss).toContain('--nc-scrollbar-thumb: #475467')
  })

  it('maps shared Element Plus surfaces to semantic tokens', () => {
    for (const selector of [
      '.el-drawer', '.el-dialog', '.el-table', '.el-input', '.el-select', '.el-tabs',
      '.el-dropdown-menu', '.el-popover.el-popper', '.el-tooltip__popper.el-popper',
      '.el-message', '.el-notification',
    ]) expect(elementPlusCss).toContain(selector)
    expect(elementPlusCss).toContain('--el-bg-color-overlay: var(--nc-bg-elevated)')
    expect(elementPlusCss).toContain('--el-table-row-hover-bg-color: var(--nc-table-hover-bg)')
  })
})
