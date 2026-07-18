import { ref } from 'vue'
import type { SystemLanguage } from '../types/systemSettings'

const locale = ref<SystemLanguage>('zh_CN')
const en: Record<string, string> = {
  'shell.console': 'Web Console', 'shell.local_console': 'Local network operations console',
  'shell.toggle_navigation': 'Toggle navigation', 'shell.subtitle': 'Vue, FastAPI, and Python share one business core',
  'shell.backend_online': 'Backend Online', 'shell.backend_offline': 'Backend Offline',
  'shell.build_mismatch': 'Web resources do not match the backend version.', 'nav.settings': 'System Settings',
  'settings.title': 'System Settings', 'settings.save': 'Save', 'settings.reload': 'Reload',
  'settings.defaults': 'Restore form defaults', 'settings.cancel': 'Cancel changes',
  'settings.appearance': 'Appearance', 'settings.tools': 'Tool paths', 'settings.terminal': 'External terminal',
  'settings.site': 'Current site', 'settings.features': 'Feature switches', 'settings.unsaved': 'Unsaved changes',
  'settings.language_block': 'BLOCKED_ON_GLOBAL_I18N: Shell and settings consume the shared runtime; business modules are not fully connected.',
  'common.yes': 'Yes', 'common.no': 'No',
  'table.no_data': 'No data', 'table.column_settings': 'Column settings',
  'table.autofit': 'Auto fit columns', 'table.reset_layout': 'Restore default layout',
  'table.pin': 'Pin position', 'table.pin_left': 'Left', 'table.pin_right': 'Right',
  'table.unpinned': 'Unpinned', 'table.move_up': 'Move up', 'table.move_down': 'Move down',
}
export function setAppLocale(value: SystemLanguage): void { locale.value = value }
export function currentAppLocale(): SystemLanguage { return locale.value }
export function t(key: string, fallback = key): string { void locale.value; return locale.value === 'en_US' ? (en[key] ?? fallback) : fallback }
export function navigationTitle(id: string, fallback: string): string { return t(`nav.${id}`, fallback) }
