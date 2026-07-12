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
})
