import type { UiPreferenceKey } from '../../../../desktop_electron/src/shared/bridge'
import { clearUiPreference, saveUiPreference } from '../../platform/uiPreferences'

export interface NcTableColumnPreference {
  key: string
  width?: number
  visible?: boolean
  fixed?: 'left' | 'right' | false
}

export interface NcTablePreferences {
  version: 1
  order: string[]
  columns: NcTableColumnPreference[]
}

export interface NcTablePreferenceColumnDefinition {
  key: string
  visible?: boolean
  hideable?: boolean
  fixed?: 'left' | 'right' | false | boolean
  minWidth?: number
  maxWidth?: number
}

export interface NcTablePreferenceIdentity {
  userKey?: string
  routeKey: string
  tableId: string
  language: string
}

const STORAGE_PREFIX = 'netconsole.table-preferences.v2'
const LEGACY_STORAGE_PREFIX = 'netconsole:table-layout:v1:'

const BRIDGE_TABLE_KEYS: Record<string, UiPreferenceKey> = {
  'mesh-analysis-sessions:v2': 'mesh-analysis.table.sessions:v2',
  'mesh-analysis-active-build-order:v2': 'mesh-analysis.table.active-build-order:v2',
  'mesh-analysis-link-details:v2': 'mesh-analysis.table.link-details:v2',
  'mesh-analysis-switch-events:v2': 'mesh-analysis.table.switch-events:v2',
  'mesh-analysis-artifacts:v2': 'mesh-analysis.table.artifacts:v2',
  'mesh-analysis-sources:v2': 'mesh-analysis.table.sources:v2',
}

function encodePart(value: string): string {
  return encodeURIComponent(value.trim() || '_')
}

export function tablePreferenceKey(identity: NcTablePreferenceIdentity): string {
  return [
    STORAGE_PREFIX,
    encodePart(identity.userKey ?? 'local-user'),
    encodePart(identity.routeKey),
    encodePart(identity.tableId),
    encodePart(identity.language),
  ].join(':')
}

function bridgeTableKey(identity: NcTablePreferenceIdentity): UiPreferenceKey | undefined {
  return BRIDGE_TABLE_KEYS[identity.tableId]
}

function isPreference(value: unknown): value is NcTablePreferences {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<NcTablePreferences>
  return candidate.version === 1
    && Array.isArray(candidate.order)
    && candidate.order.every((item) => typeof item === 'string')
    && Array.isArray(candidate.columns)
    && candidate.columns.every((item) => {
      if (!item || typeof item !== 'object') return false
      const column = item as NcTableColumnPreference
      return typeof column.key === 'string'
    })
}

function validFixed(value: unknown): value is 'left' | 'right' | false {
  return value === false || value === 'left' || value === 'right'
}

function defaultFixed(column: NcTablePreferenceColumnDefinition): 'left' | 'right' | false {
  if (column.fixed === true) return 'left'
  return validFixed(column.fixed) ? column.fixed : false
}

function validWidth(value: unknown, column: NcTablePreferenceColumnDefinition): value is number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return false
  if (column.minWidth != null && value < column.minWidth) return false
  if (column.maxWidth != null && value > column.maxWidth) return false
  return true
}

/** 以当前代码列定义为基准修复旧版、部分或空的表格偏好。 */
export function normalizeTablePreferences(
  currentColumns: readonly NcTablePreferenceColumnDefinition[],
  savedPreferences?: NcTablePreferences | null,
): NcTablePreferences {
  const current = currentColumns.filter((column, index, all) => column.key && all.findIndex((item) => item.key === column.key) === index)
  const currentByKey = new Map(current.map((column) => [column.key, column]))
  const savedByKey = new Map((isPreference(savedPreferences) ? savedPreferences.columns : []).map((column) => [column.key, column]))
  const order: string[] = []
  const seen = new Set<string>()
  for (const key of isPreference(savedPreferences) ? savedPreferences.order : []) {
    if (currentByKey.has(key) && !seen.has(key)) {
      seen.add(key)
      order.push(key)
    }
  }
  for (const column of current) {
    if (!seen.has(column.key)) {
      seen.add(column.key)
      order.push(column.key)
    }
  }
  return {
    version: 1,
    order,
    columns: order.map((key) => {
      const definition = currentByKey.get(key)!
      const saved = savedByKey.get(key)
      const preference: NcTableColumnPreference = {
        key,
        visible: definition.hideable === false ? true : saved?.visible ?? definition.visible ?? true,
        fixed: validFixed(saved?.fixed) ? saved.fixed : defaultFixed(definition),
      }
      if (validWidth(saved?.width, definition)) preference.width = saved!.width
      return preference
    }),
  }
}

export function loadTablePreferences(
  identity: NcTablePreferenceIdentity,
  storage: Pick<Storage, 'getItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): NcTablePreferences | undefined {
  if (!storage) return undefined
  try {
    const raw = storage.getItem(tablePreferenceKey(identity))
    if (raw) {
      const value: unknown = JSON.parse(raw)
      if (isPreference(value)) return value
    }
    return migrateLegacyPreference(identity, storage)
  } catch {
    return undefined
  }
}

export async function loadTablePreferencesAsync(
  identity: NcTablePreferenceIdentity,
  storage: Pick<Storage, 'getItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): Promise<NcTablePreferences | undefined> {
  const key = bridgeTableKey(identity)
  const bridge = typeof window === 'undefined' ? undefined : window.netconsoleDesktop
  if (key && bridge?.getUiPreference) {
    try {
      const value = await bridge.getUiPreference(key)
      if (isPreference(value)) return value
      const migrated = loadTablePreferences(identity, storage)
      if (migrated) await saveUiPreference(key, migrated)
      return migrated
    } catch {
      return loadTablePreferences(identity, storage)
    }
  }
  return loadTablePreferences(identity, storage)
}

export function saveTablePreferences(
  identity: NcTablePreferenceIdentity,
  preferences: NcTablePreferences,
  storage: Pick<Storage, 'setItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): void {
  if (!storage) return
  try {
    storage.setItem(tablePreferenceKey(identity), JSON.stringify(preferences))
  } catch {
    // 视图偏好写入失败不得影响业务表格使用。
  }
}

export async function saveTablePreferencesAsync(
  identity: NcTablePreferenceIdentity,
  preferences: NcTablePreferences,
  storage: Pick<Storage, 'setItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): Promise<void> {
  saveTablePreferences(identity, preferences, storage)
  const key = bridgeTableKey(identity)
  if (key) await saveUiPreference(key, preferences)
}

export function clearTablePreferences(
  identity: NcTablePreferenceIdentity,
  storage: Pick<Storage, 'removeItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): void {
  if (!storage) return
  try {
    storage.removeItem(tablePreferenceKey(identity))
  } catch {
    // 视图偏好清理失败时保留当前内存布局。
  }
}

export async function clearTablePreferencesAsync(
  identity: NcTablePreferenceIdentity,
  storage: Pick<Storage, 'removeItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): Promise<void> {
  clearTablePreferences(identity, storage)
  const key = bridgeTableKey(identity)
  if (key) await clearUiPreference(key)
}

interface LegacyStorage extends Pick<Storage, 'getItem'> {
  length?: number
  key?: (index: number) => string | null
  setItem?: (key: string, value: string) => void
}

function migrateLegacyPreference(identity: NcTablePreferenceIdentity, storage: Pick<Storage, 'getItem'>): NcTablePreferences | undefined {
  const legacy = storage as LegacyStorage
  if (legacy.length == null || !legacy.key) return undefined
  const tableBase = identity.tableId.replace(/:v2$/, '')
  let migrated: NcTablePreferences | undefined
  for (let index = 0; index < legacy.length; index += 1) {
    const key = legacy.key(index)
    if (!key?.startsWith(LEGACY_STORAGE_PREFIX)) continue
    const parts = key.split(':')
    if (parts.length !== 7) continue
    try {
      const [, , , userKey, routeKey, tableId, language] = parts.map((part) => decodeURIComponent(part))
      if (userKey !== (identity.userKey ?? 'local-user') || routeKey !== identity.routeKey || language !== identity.language) continue
      if (tableId !== tableBase && !tableId.startsWith(`${tableBase}:`)) continue
      const value: unknown = JSON.parse(storage.getItem(key) || '')
      if (isPreference(value)) migrated = value
    } catch {
      // Ignore malformed legacy entries and continue searching for a valid layout.
    }
  }
  if (migrated && legacy.setItem) {
    try { legacy.setItem(tablePreferenceKey(identity), JSON.stringify(migrated)) } catch { /* Keep the migrated layout in memory if storage is read-only. */ }
  }
  return migrated
}
