import { getSystemSettings } from '../api/systemSettings'
import { setAppLocale } from '../i18n/runtime'
import { applyNetConsoleTheme } from '../theme/theme'
import type { SystemSettingsSnapshot, SystemSettingsValues } from '../types/systemSettings'

export function applySystemAppearance(values: Pick<SystemSettingsValues, 'theme' | 'language' | 'theme_color'>): void {
  applyNetConsoleTheme(values.theme, values.theme_color)
  document.documentElement.lang = values.language === 'zh_CN' ? 'zh-CN' : 'en-US'
  setAppLocale(values.language)
}

export async function initializeSystemAppearance(
  loadSettings: () => Promise<SystemSettingsSnapshot> = getSystemSettings,
): Promise<boolean> {
  try {
    const settings = await loadSettings()
    applySystemAppearance(settings.values)
    return true
  } catch {
    // 设置页会显示受控错误；Browser/Electron 启动都保留默认外观。
    return false
  }
}
