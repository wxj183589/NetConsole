import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetPlatformRuntimeForTests } from '../platform/runtime'
import { getRendererFeatureStates, type RendererFeatureState } from './features'

interface PendingFeatureResponse {
  resolve: (snapshot: RendererFeatureState[]) => void
}

function pendingFeatureFetch(): {
  fetchMock: ReturnType<typeof vi.fn>
  responses: PendingFeatureResponse[]
} {
  const responses: PendingFeatureResponse[] = []
  const fetchMock = vi.fn(() => new Promise<Response>((resolve) => {
    responses.push({
      resolve: (snapshot) => resolve(new Response(JSON.stringify({ items: snapshot }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    })
  }))
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, responses }
}

describe('Feature API', () => {
  beforeEach(() => {
    resetPlatformRuntimeForTests()
  })

  afterEach(() => {
    resetPlatformRuntimeForTests()
    vi.unstubAllGlobals()
  })

  it('keeps normal concurrent feature GET requests coalesced', async () => {
    const { fetchMock, responses } = pendingFeatureFetch()

    const first = getRendererFeatureStates()
    const second = getRendererFeatureStates()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    responses[0].resolve([
      { feature_id: 'module.devices', visible: true, enabled: true },
    ])
    await expect(Promise.all([first, second])).resolves.toEqual([
      [{ feature_id: 'module.devices', visible: true, enabled: true }],
      [{ feature_id: 'module.devices', visible: true, enabled: true }],
    ])
  })

  it('uses a fresh GET while a normal feature request remains pending', async () => {
    const { fetchMock, responses } = pendingFeatureFetch()

    const existing = getRendererFeatureStates()
    const fresh = getRendererFeatureStates({ fresh: true })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    responses[0].resolve([
      { feature_id: 'module.ground_unattended', visible: true, enabled: true },
    ])
    responses[1].resolve([
      { feature_id: 'module.ground_unattended', visible: false, enabled: false },
    ])
    await expect(Promise.all([existing, fresh])).resolves.toEqual([
      [{ feature_id: 'module.ground_unattended', visible: true, enabled: true }],
      [{ feature_id: 'module.ground_unattended', visible: false, enabled: false }],
    ])
  })
})
