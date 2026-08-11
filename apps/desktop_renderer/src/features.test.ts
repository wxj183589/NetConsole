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

type FeatureSnapshot = Awaited<ReturnType<typeof getRendererFeatureStates>>

function deferredSnapshot(): {
  promise: Promise<FeatureSnapshot>
  resolve: (value: FeatureSnapshot) => void
  reject: (reason?: unknown) => void
} {
  let resolve!: (value: FeatureSnapshot) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<FeatureSnapshot>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const fullSnapshot: FeatureSnapshot = [
  { feature_id: 'module.devices', visible: true, enabled: true },
  { feature_id: 'module.rail_transit', visible: true, enabled: true },
  { feature_id: 'module.ground_unattended', visible: true, enabled: true },
  { feature_id: 'capability.devices.connection_test', visible: true, enabled: true },
  { feature_id: 'capability.devices.form_connection_test', visible: true, enabled: true },
]

const customerSnapshot: FeatureSnapshot = [
  { feature_id: 'module.devices', visible: true, enabled: true },
  { feature_id: 'module.rail_transit', visible: true, enabled: true },
  { feature_id: 'module.ground_unattended', visible: false, enabled: false },
  { feature_id: 'capability.devices.connection_test', visible: true, enabled: true },
  { feature_id: 'capability.devices.form_connection_test', visible: false, enabled: false },
]

function visibleNavigationIds(): string[] {
  return flattenNavigation(visibleNavigation(isFeatureVisible)).map((item) => item.navigation_id)
}

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

  it('ignores an older Full snapshot that resolves after a forced Customer refresh', async () => {
    const oldFull = deferredSnapshot()
    const currentCustomer = deferredSnapshot()
    vi.mocked(getRendererFeatureStates)
      .mockReturnValueOnce(oldFull.promise)
      .mockReturnValueOnce(currentCustomer.promise)

    const loadingOldFull = loadRendererFeatures()
    const loadingCustomer = loadRendererFeatures(true)
    currentCustomer.resolve(customerSnapshot)
    await loadingCustomer

    expect(visibleNavigationIds()).toContain('devices')
    expect(visibleNavigationIds()).not.toContain('rail.ground-unattended')
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    oldFull.resolve(fullSnapshot)
    await loadingOldFull

    expect(visibleNavigationIds()).toContain('devices')
    expect(visibleNavigationIds()).not.toContain('rail.ground-unattended')
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })

  it('does not let an older request clear the pending forced refresh', async () => {
    const oldFull = deferredSnapshot()
    const currentCustomer = deferredSnapshot()
    vi.mocked(getRendererFeatureStates)
      .mockReturnValueOnce(oldFull.promise)
      .mockReturnValueOnce(currentCustomer.promise)

    const loadingOldFull = loadRendererFeatures()
    const loadingCustomer = loadRendererFeatures(true)
    oldFull.resolve(fullSnapshot)
    await loadingOldFull

    const sharedCustomerLoad = loadRendererFeatures()
    expect(getRendererFeatureStates).toHaveBeenCalledTimes(2)
    expect(visibleNavigationIds()).toEqual(['dashboard'])
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    currentCustomer.resolve(customerSnapshot)
    await Promise.all([loadingCustomer, sharedCustomerLoad])
    expect(visibleNavigationIds()).toContain('devices')
    expect(visibleNavigationIds()).not.toContain('rail.ground-unattended')
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })

  it('commits only the latest of three out-of-order forced refreshes', async () => {
    const requestA = deferredSnapshot()
    const requestB = deferredSnapshot()
    const requestC = deferredSnapshot()
    vi.mocked(getRendererFeatureStates)
      .mockReturnValueOnce(requestA.promise)
      .mockReturnValueOnce(requestB.promise)
      .mockReturnValueOnce(requestC.promise)

    const loadingA = loadRendererFeatures()
    const loadingB = loadRendererFeatures(true)
    const loadingC = loadRendererFeatures(true)

    requestB.resolve(fullSnapshot)
    await loadingB
    expect(visibleNavigationIds()).toEqual(['dashboard'])
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    requestA.resolve(fullSnapshot)
    await loadingA
    expect(visibleNavigationIds()).toEqual(['dashboard'])
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    requestC.resolve(customerSnapshot)
    await loadingC
    expect(getRendererFeatureStates).toHaveBeenCalledTimes(3)
    expect(visibleNavigationIds()).toContain('devices')
    expect(visibleNavigationIds()).not.toContain('rail.ground-unattended')
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })

  it('ignores an older request failure after the forced refresh succeeds', async () => {
    const oldRequest = deferredSnapshot()
    const currentCustomer = deferredSnapshot()
    vi.mocked(getRendererFeatureStates)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(currentCustomer.promise)

    const loadingOldRequest = loadRendererFeatures()
    const loadingCustomer = loadRendererFeatures(true)
    currentCustomer.resolve(customerSnapshot)
    await loadingCustomer
    oldRequest.reject(new Error('stale Full snapshot failed'))

    await expect(loadingOldRequest).resolves.toBeUndefined()
    expect(visibleNavigationIds()).toContain('devices')
    expect(visibleNavigationIds()).not.toContain('rail.ground-unattended')
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
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
