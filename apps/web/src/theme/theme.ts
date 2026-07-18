import type { SystemTheme, SystemThemeColor } from '../types/systemSettings'

export type ResolvedTheme = Exclude<SystemTheme, 'auto'>

export const NETCONSOLE_THEME_CHANGE_EVENT = 'netconsole:theme-change'

const SYSTEM_DARK_QUERY = '(prefers-color-scheme: dark)'

let activeTheme: SystemTheme = 'light'
let systemQuery: MediaQueryList | null = null
let systemListener: ((event: MediaQueryListEvent) => void) | null = null

export function resolveTheme(theme: SystemTheme, prefersDark = systemPrefersDark()): ResolvedTheme {
  if (theme === 'auto') return prefersDark ? 'dark' : 'light'
  return theme
}

export function applyNetConsoleTheme(theme: SystemTheme, color: SystemThemeColor): ResolvedTheme {
  activeTheme = theme
  const resolved = resolveTheme(theme)
  const root = document.documentElement
  root.dataset.theme = resolved
  root.classList.toggle('dark', resolved === 'dark')
  root.style.setProperty('--nc-primary', color)
  root.style.setProperty('--nc-accent', color)
  bindSystemPreference(theme === 'auto')
  notifyThemeChange(resolved, color)
  syncDesktopBackground(resolved)
  return resolved
}

export function stopThemeSynchronization(): void {
  if (systemQuery && systemListener) systemQuery.removeEventListener('change', systemListener)
  systemQuery = null
  systemListener = null
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(SYSTEM_DARK_QUERY).matches
}

function bindSystemPreference(enabled: boolean): void {
  stopThemeSynchronization()
  if (!enabled || typeof window.matchMedia !== 'function') return
  systemQuery = window.matchMedia(SYSTEM_DARK_QUERY)
  systemListener = (event) => {
    if (activeTheme !== 'auto') return
    const resolved = resolveTheme('auto', event.matches)
    document.documentElement.dataset.theme = resolved
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    notifyThemeChange(resolved, document.documentElement.style.getPropertyValue('--nc-primary'))
    syncDesktopBackground(resolved)
  }
  systemQuery.addEventListener('change', systemListener)
}

function notifyThemeChange(theme: ResolvedTheme, color: string): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(NETCONSOLE_THEME_CHANGE_EVENT, { detail: { theme, color } }),
  )
}

function syncDesktopBackground(theme: ResolvedTheme): void {
  if (typeof window === 'undefined') return
  window.netconsoleDesktop?.reportRendererReady({ resolvedTheme: theme })
}
