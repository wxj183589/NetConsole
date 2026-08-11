import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getRendererFeatureStates } from './api/features'
import {
  isFeatureEnabled,
  isFeatureVisible,
  loadRendererFeatures,
  resetRendererFeaturesForTest,
  setRendererFeaturesForTest,
} from './features'

vi.mock('./api/features', () => ({ getRendererFeatureStates: vi.fn() }))

describe('Web Feature Gate', () => {
  beforeEach(() => {
    resetRendererFeaturesForTest()
    vi.mocked(getRendererFeatureStates).mockReset()
  })

  it('loads effective states from the backend', async () => {
    vi.mocked(getRendererFeatureStates).mockResolvedValue([
      { feature_id: 'module.devices', visible: false, enabled: false },
      { feature_id: 'module.file_management', visible: true, enabled: false },
    ])

    await loadRendererFeatures()

    expect(isFeatureVisible('module.devices')).toBe(false)
    expect(isFeatureEnabled('module.devices')).toBe(false)
    expect(isFeatureVisible('module.file_management')).toBe(true)
    expect(isFeatureEnabled('module.file_management')).toBe(false)
  })

  it('fails open before loading but honors explicit test states', () => {
    expect(isFeatureVisible('module.devices')).toBe(true)
    setRendererFeaturesForTest({ 'module.devices': { visible: false, enabled: false } })
    expect(isFeatureVisible('module.devices')).toBe(false)
  })
})
