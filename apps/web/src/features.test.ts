import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getWebFeatureStates } from './api/features'
import {
  isFeatureEnabled,
  isFeatureVisible,
  loadWebFeatures,
  resetWebFeaturesForTest,
  setWebFeaturesForTest,
} from './features'

vi.mock('./api/features', () => ({ getWebFeatureStates: vi.fn() }))

describe('Web Feature Gate', () => {
  beforeEach(() => {
    resetWebFeaturesForTest()
    vi.mocked(getWebFeatureStates).mockReset()
  })

  it('loads effective states from the backend', async () => {
    vi.mocked(getWebFeatureStates).mockResolvedValue([
      { feature_id: 'web.device_management', visible: false, enabled: false },
      { feature_id: 'web.file_management', visible: true, enabled: false },
    ])

    await loadWebFeatures()

    expect(isFeatureVisible('web.device_management')).toBe(false)
    expect(isFeatureEnabled('web.device_management')).toBe(false)
    expect(isFeatureVisible('web.file_management')).toBe(true)
    expect(isFeatureEnabled('web.file_management')).toBe(false)
  })

  it('fails open before loading but honors explicit test states', () => {
    expect(isFeatureVisible('web.device_management')).toBe(true)
    setWebFeaturesForTest({ 'web.device_management': { visible: false, enabled: false } })
    expect(isFeatureVisible('web.device_management')).toBe(false)
  })
})
