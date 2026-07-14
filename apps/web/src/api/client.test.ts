import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from './client'

describe('API client errors', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows standardized backend message without exposing stack details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ ok: false, error: { code: 'AGENT_TIMEOUT', message: '连接 Agent 超时' } }),
    }))
    await expect(apiRequest('/api/agents/probe')).rejects.toThrow('连接 Agent 超时')
  })

  it('leaves multipart content type to the browser so the boundary is preserved', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const body = new FormData()
    body.append('file', 'preview')

    await apiRequest('/api/rail-transit/base-data/import-preview', { method: 'POST', body })

    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.has('Content-Type')).toBe(false)
  })
})
