import { NETCONSOLE_THEME_CHANGE_EVENT } from './theme'

export interface NetConsoleChartTokens {
  series: string[]
  text: string
  textSecondary: string
  background: string
  border: string
  splitLine: string
  primary: string
  warning: string
  danger: string
  info: string
}

const FALLBACKS = {
  primary: '#1677ff',
  success: '#52c41a',
  warning: '#faad14',
  danger: '#ff4d4f',
  info: '#909399',
  text: '#1f2329',
  textSecondary: '#606266',
  background: '#ffffff',
  border: '#dcdfe6',
  splitLine: '#ebeef5',
} as const

export function readNetConsoleChartTokens(): NetConsoleChartTokens {
  const styles = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
  const primary = read('--nc-primary', FALLBACKS.primary)
  const warning = read('--nc-warning', FALLBACKS.warning)
  const danger = read('--nc-danger', FALLBACKS.danger)
  const info = read('--nc-info', FALLBACKS.info)

  return {
    series: [primary, read('--nc-success', FALLBACKS.success), warning, danger, info],
    text: read('--nc-text-primary', FALLBACKS.text),
    textSecondary: read('--nc-text-secondary', FALLBACKS.textSecondary),
    background: read('--nc-bg-elevated', FALLBACKS.background),
    border: read('--nc-border', FALLBACKS.border),
    splitLine: read('--nc-border-light', FALLBACKS.splitLine),
    primary,
    warning,
    danger,
    info,
  }
}

export function subscribeNetConsoleChartTheme(listener: () => void): () => void {
  window.addEventListener(NETCONSOLE_THEME_CHANGE_EVENT, listener)
  return () => window.removeEventListener(NETCONSOLE_THEME_CHANGE_EVENT, listener)
}
