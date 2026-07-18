import { describe, expect, it, vi } from 'vitest'

import {
  clearTablePreferences,
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
})
