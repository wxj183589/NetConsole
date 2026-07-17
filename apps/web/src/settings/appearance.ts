import { setAppLocale } from '../i18n/runtime'
import type { SystemSettingsValues } from '../types/systemSettings'

export function applySystemAppearance(values: Pick<SystemSettingsValues, 'theme' | 'language' | 'theme_color'>): void {
  const dark = values.theme === 'dark' || (values.theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.lang = values.language === 'zh_CN' ? 'zh-CN' : 'en-US'
  document.documentElement.style.setProperty('--nc-accent', values.theme_color)
  document.documentElement.style.setProperty('--el-color-primary', values.theme_color)
  setAppLocale(values.language)
}
