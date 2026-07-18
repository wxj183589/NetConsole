// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

import { applyNetConsoleTheme } from './theme'
import { readNetConsoleChartTokens, subscribeNetConsoleChartTheme } from './echarts'

afterEach(() => {
  document.documentElement.removeAttribute('style')
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.className = ''
  vi.restoreAllMocks()
})

describe('NetConsole ECharts theme bridge', () => {
  it('reads chart colors from the active design tokens', () => {
    const root = document.documentElement
    root.style.setProperty('--nc-primary', '#2563eb')
    root.style.setProperty('--nc-success', '#16a34a')
    root.style.setProperty('--nc-text-primary', '#f8fafc')
    root.style.setProperty('--nc-border-light', '#334155')

    const tokens = readNetConsoleChartTokens()

    expect(tokens.series.slice(0, 2)).toEqual(['#2563eb', '#16a34a'])
    expect(tokens.text).toBe('#f8fafc')
    expect(tokens.splitLine).toBe('#334155')
  })

  it('notifies mounted charts when appearance changes after bootstrap', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    const listener = vi.fn()
    const unsubscribe = subscribeNetConsoleChartTheme(listener)

    applyNetConsoleTheme('dark', '#2563EB')

    expect(listener).toHaveBeenCalledOnce()
    unsubscribe()
    applyNetConsoleTheme('light', '#0078D4')
    expect(listener).toHaveBeenCalledOnce()
  })
})
