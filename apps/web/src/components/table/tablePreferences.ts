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

export interface NcTablePreferenceIdentity {
  userKey?: string
  routeKey: string
  tableId: string
  language: string
}

const STORAGE_PREFIX = 'netconsole:table-layout:v1'

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
        && (column.width == null || (Number.isFinite(column.width) && column.width > 0))
        && (column.visible == null || typeof column.visible === 'boolean')
        && (column.fixed == null || column.fixed === false || column.fixed === 'left' || column.fixed === 'right')
    })
}

export function loadTablePreferences(
  identity: NcTablePreferenceIdentity,
  storage: Pick<Storage, 'getItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): NcTablePreferences | undefined {
  if (!storage) return undefined
  try {
    const raw = storage.getItem(tablePreferenceKey(identity))
    if (!raw) return undefined
    const value: unknown = JSON.parse(raw)
    return isPreference(value) ? value : undefined
  } catch {
    return undefined
  }
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
