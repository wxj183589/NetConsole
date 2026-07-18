import { getSystemSettings } from '../api/systemSettings'
import { setAppLocale } from '../i18n/runtime'
import { applyNetConsoleTheme, type ApplyThemeOptions } from '../theme/theme'
import type { SystemSettingsSnapshot, SystemSettingsValues } from '../types/systemSettings'

export const SAFE_SYSTEM_APPEARANCE = Object.freeze({
  theme: 'light',
  language: 'zh_CN',
  theme_color: '#0078D4',
} satisfies Pick<SystemSettingsValues, 'theme' | 'language' | 'theme_color'>)

export function applySystemAppearance(
  values: Pick<SystemSettingsValues, 'theme' | 'language' | 'theme_color'>,
  options: ApplyThemeOptions = {},
): void {
  applyNetConsoleTheme(values.theme, values.theme_color, options)
  document.documentElement.lang = values.language === 'zh_CN' ? 'zh-CN' : 'en-US'
  setAppLocale(values.language)
}

export function applySafeSystemAppearance(): void {
  // 只为首屏 DOM 建立不可见的故障默认；不得把它误报为已持久化主题。
  applySystemAppearance(SAFE_SYSTEM_APPEARANCE, { reportDesktop: false })
}

export async function initializeSystemAppearance(
  loadSettings: () => Promise<SystemSettingsSnapshot> = getSystemSettings,
): Promise<boolean> {
  try {
    const settings = await loadSettings()
    applySystemAppearance(settings.values)
    return true
  } catch {
    // 设置页会显示受控错误；Browser/Electron 启动都回落到完整安全浅色。
    applySystemAppearance(SAFE_SYSTEM_APPEARANCE)
    return false
  }
}
