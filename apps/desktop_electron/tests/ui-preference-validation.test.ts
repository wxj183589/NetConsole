import { describe, expect, it } from 'vitest'

import { UI_PREFERENCE_KEYS } from '../src/shared/bridge'
import {
  validateUiPreferenceKey,
  validateUiPreferenceValue,
} from '../src/shared/validation'

describe('UI preference validation', () => {
  it('allowlists the layout keys and accepts only the three layout modes', () => {
    expect(UI_PREFERENCE_KEYS).toContain('mesh-analysis-rssi.layout-mode')
    expect(validateUiPreferenceKey('mesh-analysis-rssi.layout-mode')).toBe(
      'mesh-analysis-rssi.layout-mode',
    )
    for (const mode of ['compare', 'active-focus', 'trackside-focus']) {
      expect(validateUiPreferenceValue(
        'mesh-analysis-rssi.layout-mode',
        mode,
      )).toBe(mode)
    }
    expect(() => validateUiPreferenceValue(
      'mesh-analysis-rssi.layout-mode',
      'fullscreen',
    )).toThrow('UI RSSI layout preference is invalid')
  })

  it('allowlists versioned device table preferences and validates their shape', () => {
    const preference = {
      version: 1,
      order: ['name', 'status'],
      columns: [
        { key: 'name', width: 220, visible: true, fixed: 'left' },
        { key: 'status', visible: false, fixed: false },
      ],
    }
    for (const key of [
      'device-management.device-list',
      'device-detail.interfaces',
      'device-detail.optical-modules',
      'device-detail.lldp',
      'device-detail.task-records',
      'device-detail.related-businesses',
      'rail.trackside-ap-business.table.main',
      'rail.trackside-ap-business.table.scope-excluded',
      'rail.trackside-ap-business.table.unmatched-online',
    ] as const) {
      expect(validateUiPreferenceKey(key)).toBe(key)
      expect(validateUiPreferenceValue(key, preference)).toEqual(preference)
    }
    expect(() => validateUiPreferenceValue(
      'device-detail.interfaces',
      { ...preference, version: 2 },
    )).toThrow('table preference version is invalid')
  })

  it('accepts only finite split ratios from 0.25 through 0.75', () => {
    expect(UI_PREFERENCE_KEYS).toContain('mesh-analysis-rssi.compare-split-ratio')
    for (const ratio of [0.25, 0.5, 0.75]) {
      expect(validateUiPreferenceValue(
        'mesh-analysis-rssi.compare-split-ratio',
        ratio,
      )).toBe(ratio)
    }
    for (const ratio of [0.249, 0.751, Number.NaN, '0.5']) {
      expect(() => validateUiPreferenceValue(
        'mesh-analysis-rssi.compare-split-ratio',
        ratio,
      )).toThrow('UI RSSI split preference is invalid')
    }
  })
})
