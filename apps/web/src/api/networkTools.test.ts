import { describe, expect, it, vi } from 'vitest'

import { startTcpPortTest } from './networkTools'

describe('network tools API client', () => {
  it('posts the whitelisted TCP probe payload to the independent API', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ run: { traffic_run_id: 'tcp-1' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const payload = {
      execution_target: { kind: 'LOCAL' as const },
      target: '127.0.0.1',
      port: 443,
      interval_ms: 250,
      timeout_ms: 500,
      count: 2,
    }

    await startTcpPortTest(payload)

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/network-tools/tcp-port-test')
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(payload)
  })
})
