import { afterEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  getHealth: vi.fn(),
}))

vi.mock('./client', async (importOriginal) => {
  const original = await importOriginal<typeof import('./client')>()
  return {
    ...original,
    apiRequest: client.apiRequest,
    getHealth: client.getHealth,
  }
})

import { ApiRequestError } from './client'
import { probeGroundSyslogTransportState } from './groundUnattended'

describe('ground unattended Syslog failure classification', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('rechecks health and reports an interrupted query while Backend stays online', async () => {
    client.getHealth.mockResolvedValue({
      status: 'ok',
      version: 'v1.4.6',
      build_id: 'test',
    })

    const result = await probeGroundSyslogTransportState(
      new ApiRequestError(
        'Backend 连接中断，请重试。',
        0,
        'BACKEND_CONNECTION_INTERRUPTED',
      ),
    )

    expect(client.getHealth).toHaveBeenCalledOnce()
    expect(result).toEqual({
      code: 'BACKEND_CONNECTION_INTERRUPTED',
      requestId: '',
      backendState: 'ONLINE',
    })
  })

  it('only reports Backend unreachable when the health recheck fails', async () => {
    client.getHealth.mockRejectedValue(new Error('health failed'))

    const result = await probeGroundSyslogTransportState(
      new ApiRequestError(
        'Backend 连接中断，请重试。',
        0,
        'CONNECTION_RESET',
        { request_id: 'request-1' },
      ),
    )

    expect(result).toEqual({
      code: 'BACKEND_UNREACHABLE',
      requestId: 'request-1',
      backendState: 'OFFLINE',
    })
  })

  it.each(['RAW_QUERY_TIMEOUT', 'BACKEND_RESTARTED'])(
    'rechecks health while preserving the %s classification',
    async (code) => {
      client.getHealth.mockResolvedValue({
        status: 'ok',
        version: 'v1.4.6',
        build_id: 'test',
      })

      const result = await probeGroundSyslogTransportState(
        new ApiRequestError('Backend 连接中断，请重试。', 0, code),
      )

      expect(client.getHealth).toHaveBeenCalledOnce()
      expect(result).toEqual({
        code,
        requestId: '',
        backendState: 'ONLINE',
      })
    },
  )

  it('keeps HTTP and response-body failures separate without probing health', async () => {
    const result = await probeGroundSyslogTransportState(
      new ApiRequestError(
        'Backend 返回内容不完整，请重试。',
        200,
        'INVALID_JSON_RESPONSE',
        { request_id: 'request-2' },
      ),
    )

    expect(client.getHealth).not.toHaveBeenCalled()
    expect(result).toEqual({
      code: 'INVALID_JSON_RESPONSE',
      requestId: 'request-2',
      backendState: 'ONLINE',
    })
  })
})
