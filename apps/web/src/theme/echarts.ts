import { NETCONSOLE_THEME_CHANGE_EVENT } from './theme'

export interface NetConsoleChartTokens {
  series: string[]
  text: string
  textSecondary: string
  background: string
  backgroundMuted: string
  border: string
  splitLine: string
  active: string
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
  backgroundMuted: '#f2f4f7',
  border: '#dcdfe6',
  splitLine: '#ebeef5',
  active: '#e8f1ff',
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
    backgroundMuted: read('--nc-bg-muted', FALLBACKS.backgroundMuted),
    border: read('--nc-border', FALLBACKS.border),
    splitLine: read('--nc-border-light', FALLBACKS.splitLine),
    active: read('--nc-bg-active', FALLBACKS.active),
    primary,
    warning,
    danger,
    info,
  }
}

export function createNetConsoleAxisStyle(theme: NetConsoleChartTokens) {
  return {
    axisLabel: { color: theme.textSecondary },
    axisLine: { lineStyle: { color: theme.border } },
    axisTick: { lineStyle: { color: theme.border } },
    splitLine: { lineStyle: { color: theme.splitLine } },
  }
}

export function createNetConsoleTooltipStyle(theme: NetConsoleChartTokens) {
  return {
    backgroundColor: theme.background,
    borderColor: theme.border,
    textStyle: { color: theme.text },
  }
}

export function createNetConsoleLegendStyle(theme: NetConsoleChartTokens) {
  return { textStyle: { color: theme.textSecondary } }
}

export function createNetConsoleDataZoomStyle(theme: NetConsoleChartTokens) {
  return {
    backgroundColor: theme.backgroundMuted,
    fillerColor: theme.active,
    borderColor: theme.border,
    textStyle: { color: theme.textSecondary },
    dataBackground: { lineStyle: { color: theme.info }, areaStyle: { color: theme.backgroundMuted } },
    selectedDataBackground: { lineStyle: { color: theme.primary }, areaStyle: { color: theme.active } },
    handleStyle: { color: theme.background, borderColor: theme.primary },
    moveHandleStyle: { color: theme.primary },
    emphasis: { handleStyle: { color: theme.primary, borderColor: theme.primary } },
  }
}

export function subscribeNetConsoleChartTheme(listener: () => void): () => void {
  window.addEventListener(NETCONSOLE_THEME_CHANGE_EVENT, listener)
  return () => window.removeEventListener(NETCONSOLE_THEME_CHANGE_EVENT, listener)
}
