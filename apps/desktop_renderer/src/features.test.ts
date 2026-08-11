import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getRendererFeatureStates } from './api/features'
import { flattenNavigation, visibleNavigation } from './navigation/registry'
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

  it('fails closed for every gated capability before the backend snapshot is loaded', () => {
    expect(isFeatureVisible('module.devices')).toBe(false)
    expect(isFeatureEnabled('module.devices')).toBe(false)
    expect(isFeatureVisible('internal.feature_switch')).toBe(false)
    expect(isFeatureEnabled('internal.feature_switch')).toBe(false)
    setRendererFeaturesForTest({ 'module.devices': { visible: false, enabled: false } })
    expect(isFeatureVisible('module.devices')).toBe(false)
  })

  it('does not retain Full-only controls while a Customer relock snapshot is pending', async () => {
    setRendererFeaturesForTest({
      'module.devices': { visible: true, enabled: true },
      'module.ground_unattended': { visible: true, enabled: true },
      'capability.devices.connection_test': { visible: true, enabled: true },
      'capability.devices.form_connection_test': { visible: true, enabled: true },
    })
    let resolveSnapshot!: (items: Array<{ feature_id: string, visible: boolean, enabled: boolean }>) => void
    vi.mocked(getRendererFeatureStates).mockReturnValue(new Promise<Array<{
      feature_id: string
      visible: boolean
      enabled: boolean
    }>>((resolve) => {
      resolveSnapshot = resolve
    }))

    const loading = loadRendererFeatures(true)

    expect(flattenNavigation(visibleNavigation(isFeatureVisible)).map((item) => item.navigation_id)).toEqual(['dashboard'])
    expect(isFeatureVisible('module.devices')).toBe(false)
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    resolveSnapshot([
      { feature_id: 'module.devices', visible: true, enabled: true },
      { feature_id: 'module.ground_unattended', visible: false, enabled: false },
      { feature_id: 'capability.devices.connection_test', visible: true, enabled: true },
      { feature_id: 'capability.devices.form_connection_test', visible: false, enabled: false },
    ])
    await loading

    const customerNavigation = flattenNavigation(visibleNavigation(isFeatureVisible)).map((item) => item.navigation_id)
    expect(customerNavigation).toContain('devices')
    expect(customerNavigation).not.toContain('rail.ground-unattended')
    expect(isFeatureVisible('module.devices')).toBe(true)
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })

  it('remains fail-closed when a forced Customer snapshot refresh fails', async () => {
    setRendererFeaturesForTest({
      'module.ground_unattended': { visible: true, enabled: true },
      'capability.devices.form_connection_test': { visible: true, enabled: true },
    })
    vi.mocked(getRendererFeatureStates).mockRejectedValue(new Error('unavailable'))

    await expect(loadRendererFeatures(true)).rejects.toThrow('unavailable')

    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
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
