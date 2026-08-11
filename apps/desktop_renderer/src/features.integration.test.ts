import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  isFeatureEnabled,
  isFeatureVisible,
  loadRendererFeatures,
  resetRendererFeaturesForTest,
} from './features'
import { resetPlatformRuntimeForTests } from './platform/runtime'

interface FeatureSnapshotItem {
  feature_id: string
  visible: boolean
  enabled: boolean
}

interface PendingFeatureResponse {
  resolve: (snapshot: FeatureSnapshotItem[]) => void
  fail: () => void
}

const fullSnapshot: FeatureSnapshotItem[] = [
  { feature_id: 'module.devices', visible: true, enabled: true },
  { feature_id: 'module.ground_unattended', visible: true, enabled: true },
  { feature_id: 'capability.devices.connection_test', visible: true, enabled: true },
  { feature_id: 'capability.devices.form_connection_test', visible: true, enabled: true },
]

const customerSnapshot: FeatureSnapshotItem[] = [
  { feature_id: 'module.devices', visible: true, enabled: true },
  { feature_id: 'module.ground_unattended', visible: false, enabled: false },
  { feature_id: 'capability.devices.connection_test', visible: true, enabled: true },
  { feature_id: 'capability.devices.form_connection_test', visible: false, enabled: false },
]

function jsonResponse(snapshot: FeatureSnapshotItem[]): Response {
  return new Response(JSON.stringify({ items: snapshot }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function pendingFeatureFetch(): {
  fetchMock: ReturnType<typeof vi.fn>
  responses: PendingFeatureResponse[]
} {
  const responses: PendingFeatureResponse[] = []
  const fetchMock = vi.fn(() => new Promise<Response>((resolve) => {
    responses.push({
      resolve: (snapshot) => resolve(jsonResponse(snapshot)),
      fail: () => resolve(new Response(JSON.stringify({ detail: 'unavailable' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      })),
    })
  }))
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, responses }
}

describe('Feature snapshot request integration', () => {
  beforeEach(() => {
    resetRendererFeaturesForTest()
    resetPlatformRuntimeForTests()
  })

  afterEach(() => {
    resetRendererFeaturesForTest()
    resetPlatformRuntimeForTests()
    vi.unstubAllGlobals()
  })

  it('fetches a fresh Customer snapshot while an older Full GET remains pending', async () => {
    const { fetchMock, responses } = pendingFeatureFetch()

    const loadingOldFull = loadRendererFeatures()
    const loadingCustomer = loadRendererFeatures(true)

    if (fetchMock.mock.calls.length !== 2) {
      responses[0].resolve(fullSnapshot)
      await Promise.all([loadingOldFull, loadingCustomer])
    }
    expect(fetchMock).toHaveBeenCalledTimes(2)

    responses[1].resolve(customerSnapshot)
    await loadingCustomer
    expect(isFeatureVisible('module.devices')).toBe(true)
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    responses[0].resolve(fullSnapshot)
    await loadingOldFull
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })

  it('fetches a fresh Full snapshot while an older Customer GET remains pending', async () => {
    const { fetchMock, responses } = pendingFeatureFetch()

    const loadingOldCustomer = loadRendererFeatures()
    const loadingFull = loadRendererFeatures(true)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    responses[1].resolve(fullSnapshot)
    await loadingFull
    expect(isFeatureVisible('module.devices')).toBe(true)
    expect(isFeatureVisible('module.ground_unattended')).toBe(true)
    expect(isFeatureEnabled('capability.devices.connection_test')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(true)

    responses[0].resolve(customerSnapshot)
    await loadingOldCustomer
    expect(isFeatureVisible('module.ground_unattended')).toBe(true)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(true)
  })

  it('does not reuse the older Full GET after a fresh Customer request fails', async () => {
    const { fetchMock, responses } = pendingFeatureFetch()

    const loadingOldFull = loadRendererFeatures()
    const loadingCustomer = loadRendererFeatures(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    responses[1].fail()
    await expect(loadingCustomer).rejects.toMatchObject({ status: 500 })
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    const loadingCustomerRetry = loadRendererFeatures()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    responses[2].resolve(customerSnapshot)
    await loadingCustomerRetry
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)

    responses[0].resolve(fullSnapshot)
    await loadingOldFull
    expect(isFeatureVisible('module.ground_unattended')).toBe(false)
    expect(isFeatureEnabled('capability.devices.form_connection_test')).toBe(false)
  })
})
