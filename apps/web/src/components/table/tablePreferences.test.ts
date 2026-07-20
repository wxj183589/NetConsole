// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'

import {
  clearTablePreferences,
  loadTablePreferencesAsync,
  loadTablePreferences,
  saveTablePreferences,
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
      getItem: () => JSON.stringify({ version: 1, order: [], columns: [{ key: 'name', width: -1 }] }),
    })).toBeUndefined()
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
})
