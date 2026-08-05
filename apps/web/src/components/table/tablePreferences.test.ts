// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'

import {
  clearTablePreferences,
  clearTablePreferencesAsync,
  loadTablePreferencesAsync,
  loadTablePreferences,
  MESH_LINK_DETAILS_V2_DEFAULT_ORDER,
  migrateVersionedPreference,
  reconcileTablePreferences,
  saveTablePreferences,
  saveTablePreferencesAsync,
  tablePreferenceKey,
  type NcTablePreferenceIdentity,
  type NcTablePreferences,
} from './tablePreferences'

const identity: NcTablePreferenceIdentity = {
  userKey: 'operator',
  routeKey: '/devices',
  tableId: 'device-list',
  language: 'zh-CN',
}

const preference: NcTablePreferences = {
  version: 1,
  order: ['name'],
  columns: [{ key: 'name', width: 220, visible: true, fixed: 'left' }],
}

describe('table preferences', () => {
  const columns = [
    { key: 'name', visible: true, hideable: true, minWidth: 120 },
    { key: 'status', visible: true, hideable: true, fixed: 'right' as const },
    { key: 'actions', visible: true, hideable: false, fixed: 'right' as const },
  ]

  it('normalizes partial and empty layouts against the complete current column set', () => {
    expect(reconcileTablePreferences(columns, {
      version: 1,
      order: ['status', 'status', 'removed'],
      columns: [
        { key: 'status', visible: false, fixed: false },
        { key: 'calculation_status', width: 230, visible: true, fixed: false },
      ],
    })).toEqual({
      version: 1,
      order: ['status', 'name', 'actions'],
      columns: [
        { key: 'status', visible: false, fixed: false },
        { key: 'name', visible: true, fixed: false },
        { key: 'actions', visible: true, fixed: 'right' },
      ],
    })
    expect(reconcileTablePreferences(columns, { version: 1, order: [], columns: [] }).columns.map((item) => item.key))
      .toEqual(['name', 'status', 'actions'])
  })

  it('falls back to defaults when a saved column contains invalid runtime values', () => {
    const normalized = reconcileTablePreferences(columns, {
      version: 1,
      order: ['name', 'status', 'actions'],
      columns: [
        { key: 'name', width: 80, visible: false, fixed: 'bad' as 'left' },
        { key: 'status', width: 180, visible: false, fixed: 'left' },
        { key: 'actions', visible: false, fixed: 'right' },
      ],
    })
    expect(normalized.columns).toEqual([
      { key: 'name', visible: true, fixed: false },
      { key: 'status', visible: true, fixed: 'right' },
      { key: 'actions', visible: true, fixed: 'right' },
    ])
  })

  it('isolates layouts by user, route, table and language', () => {
    const key = tablePreferenceKey(identity)
    expect(key).toContain('operator')
    expect(key).toContain('%2Fdevices')
    expect(key).toContain('device-list')
    expect(tablePreferenceKey({ ...identity, language: 'en-US' })).not.toBe(key)
  })

  it('persists valid view-only preferences without a business database', () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: vi.fn((key: string) => values.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => values.set(key, value)),
      removeItem: vi.fn((key: string) => values.delete(key)),
    }
    saveTablePreferences(identity, preference, storage)
    expect(loadTablePreferences(identity, storage)).toEqual(preference)
    clearTablePreferences(identity, storage)
    expect(loadTablePreferences(identity, storage)).toBeUndefined()
  })

  it('ignores damaged or structurally invalid preferences', () => {
    expect(loadTablePreferences(identity, { getItem: () => '{broken' })).toBeUndefined()
    expect(loadTablePreferences(identity, {
      getItem: () => JSON.stringify({ version: 2, order: ['name'], columns: [] }),
    })).toBeUndefined()
    expect(loadTablePreferences(identity, {
      getItem: () => JSON.stringify({ version: 1, order: [], columns: [{ key: 'name', width: -1 }] }),
    })).toBeUndefined()
    expect(loadTablePreferences(identity, {
      getItem: () => JSON.stringify({ version: 1, order: [], columns: [{ key: 'name', visible: 'yes' }] }),
    })).toBeUndefined()
  })

  it('uses stable isolated Electron keys for device and trackside AP tables', async () => {
    const tableKeys = new Map([
      ['device-list', 'device-management.device-list'],
      ['device-detail-sections:interfaces', 'device-detail.interfaces'],
      ['device-detail-sections:optical', 'device-detail.optical-modules'],
      ['device-detail-sections:lldp', 'device-detail.lldp'],
      ['device-detail-sections:tasks', 'device-detail.task-records'],
      ['device-detail-sections:business', 'device-detail.related-businesses'],
      ['trackside-ap-business', 'rail.trackside-ap-business.table.main'],
      ['trackside-ap-business-scope-excluded', 'rail.trackside-ap-business.table.scope-excluded'],
      ['trackside-ap-business-unmatched-online', 'rail.trackside-ap-business.table.unmatched-online'],
    ])
    const getUiPreference = vi.fn().mockResolvedValue(preference)
    const setUiPreference = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { getUiPreference, setUiPreference },
    })

    try {
      for (const [tableId, key] of tableKeys) {
        const tableIdentity = { ...identity, tableId }
        await expect(loadTablePreferencesAsync(tableIdentity)).resolves.toEqual(preference)
        expect(getUiPreference).toHaveBeenLastCalledWith(key)
        await saveTablePreferencesAsync(tableIdentity, preference)
        expect(setUiPreference).toHaveBeenLastCalledWith(key, preference)
        await clearTablePreferencesAsync(tableIdentity)
        expect(setUiPreference).toHaveBeenLastCalledWith(key, null)
      }
    } finally {
      Reflect.deleteProperty(window, 'netconsoleDesktop')
      localStorage.clear()
    }
  })

  it('migrates a valid legacy session layout to the stable table key', () => {
    const values = new Map<string, string>()
    const legacyKey = [
      'netconsole', 'table-layout', 'v1', 'operator', encodeURIComponent('/devices'),
      encodeURIComponent('mesh-analysis-active-build-order:session-1'), 'zh-CN',
    ].join(':')
    values.set(legacyKey, JSON.stringify(preference))
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      get length() { return values.size },
      key: (index: number) => [...values.keys()][index] ?? null,
    }

    expect(loadTablePreferences({
      ...identity,
      tableId: 'mesh-analysis-active-build-order:v2',
    }, storage)).toEqual(preference)
    expect(values.has(tablePreferenceKey({
      ...identity,
      tableId: 'mesh-analysis-active-build-order:v2',
    }))).toBe(true)
  })

  it('hydrates an Electron preference from the current legacy storage on first upgrade', async () => {
    const values = new Map<string, string>()
    values.set([
      'netconsole', 'table-layout', 'v1', 'operator', encodeURIComponent('/devices'),
      encodeURIComponent('mesh-analysis-active-build-order:session-1'), 'zh-CN',
    ].join(':'), JSON.stringify(preference))
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      get length() { return values.size },
      key: (index: number) => [...values.keys()][index] ?? null,
    }
    const setUiPreference = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { getUiPreference: vi.fn().mockResolvedValue(null), setUiPreference },
    })
    const meshIdentity = { ...identity, tableId: 'mesh-analysis-active-build-order:v2' }

    await expect(loadTablePreferencesAsync(meshIdentity, storage)).resolves.toEqual(preference)
    expect(setUiPreference).toHaveBeenCalledWith('mesh-analysis.table.active-build-order:v2', preference)
    Reflect.deleteProperty(window, 'netconsoleDesktop')
  })

  it('migrates an unchanged or incomplete v2 link layout to the v3 default order while retaining widths and visibility', () => {
    const meshIdentity = { ...identity, tableId: 'mesh-analysis-link-details:v3' }
    const migrated = migrateVersionedPreference(meshIdentity, {
      version: 1,
      order: [...MESH_LINK_DETAILS_V2_DEFAULT_ORDER],
      columns: [
        { key: 'timestamp_tag', width: 160, visible: false, fixed: 'left' },
        { key: 'local_rssi_db', width: 180, visible: true, fixed: false },
      ],
    })

    expect(migrated.order).toEqual([])
    expect(migrated.columns).toEqual([
      { key: 'timestamp_tag', width: 160, visible: false },
      { key: 'local_rssi_db', width: 180, visible: true },
    ])
    expect(migrateVersionedPreference(meshIdentity, {
      version: 1,
      order: ['timestamp', 'local_rssi_db'],
      columns: [{ key: 'local_rssi_db', visible: true }],
    }).order).toEqual([])
  })

  it('retains a complete v2 order only when it differs from the former default', () => {
    const customOrder = [...MESH_LINK_DETAILS_V2_DEFAULT_ORDER]
    ;[customOrder[0], customOrder[1]] = [customOrder[1], customOrder[0]]
    const value: NcTablePreferences = { version: 1, order: customOrder, columns: [] }

    expect(migrateVersionedPreference({ ...identity, tableId: 'mesh-analysis-link-details:v3' }, value).order)
      .toEqual(customOrder)
  })

  it('hydrates the v3 Electron key from the v2 bridge preference', async () => {
    const oldValue: NcTablePreferences = {
      version: 1,
      order: [...MESH_LINK_DETAILS_V2_DEFAULT_ORDER],
      columns: [{ key: 'local_rssi_db', width: 180, visible: true, fixed: false }],
    }
    const getUiPreference = vi.fn(async (key: string) => key === 'mesh-analysis.table.link-details:v2' ? oldValue : null)
    const setUiPreference = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { getUiPreference, setUiPreference },
    })

    const migrated = await loadTablePreferencesAsync({
      ...identity,
      routeKey: '/rail-transit/mesh-analysis',
      tableId: 'mesh-analysis-link-details:v3',
    })

    expect(getUiPreference).toHaveBeenCalledWith('mesh-analysis.table.link-details:v3')
    expect(getUiPreference).toHaveBeenCalledWith('mesh-analysis.table.link-details:v2')
    expect(migrated?.order).toEqual([])
    expect(setUiPreference).toHaveBeenCalledWith('mesh-analysis.table.link-details:v3', migrated)
    Reflect.deleteProperty(window, 'netconsoleDesktop')
  })
})
