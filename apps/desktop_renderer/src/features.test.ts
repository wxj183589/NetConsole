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

describe('Desktop Renderer Feature Gate', () => {
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

  it('fails open for public features before loading but keeps internal features hidden', () => {
    expect(isFeatureVisible('module.devices')).toBe(true)
    expect(isFeatureVisible('internal.feature_switch')).toBe(false)
    expect(isFeatureEnabled('internal.feature_switch')).toBe(false)
    setRendererFeaturesForTest({ 'module.devices': { visible: false, enabled: false } })
    expect(isFeatureVisible('module.devices')).toBe(false)
  })

  it('fails closed for feature ids omitted from a loaded backend snapshot', async () => {
    vi.mocked(getRendererFeatureStates).mockResolvedValue([
      { feature_id: 'module.devices', visible: true, enabled: true },
    ])

    await loadRendererFeatures()

    expect(isFeatureVisible('internal.feature_switch')).toBe(false)
    expect(isFeatureEnabled('internal.feature_switch')).toBe(false)
    expect(isFeatureVisible('module.unknown')).toBe(false)
    expect(isFeatureEnabled('module.unknown')).toBe(false)
  })
})
