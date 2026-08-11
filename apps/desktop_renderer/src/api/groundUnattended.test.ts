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
import {
  deleteGroundRunHistory,
  getGroundPingSeriesIncremental,
  getGroundSyslogTransportStatus,
  listGroundTimeline,
  previewGroundSyslogDelete,
  listGroundMrRuntimeStatus,
  listGroundSyslogRecords,
  probeGroundSyslogTransportState,
  submitGroundSyslogDelete,
} from './groundUnattended'

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

  it('uses dedicated read-only Transport and incremental Ping endpoints', async () => {
    client.apiRequest.mockResolvedValue({})

    await getGroundSyslogTransportStatus({ signal: new AbortController().signal })
    await getGroundPingSeriesIncremental({
      run_id: 'run-1',
      train_id: '列车07',
      mr_id: 'mr-ct',
      target_ip: '10.122.7.249',
      query_identity: 'gpq1.stable-target',
      cursor: 'cursor-1',
      max_points: 200,
    })

    expect(client.apiRequest).toHaveBeenNthCalledWith(
      1,
      '/api/rail-transit/ground-unattended/syslog-transport-status',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(String(client.apiRequest.mock.calls[1][0])).toContain('/ping-series/incremental?')
    expect(String(client.apiRequest.mock.calls[1][0])).toContain('cursor=cursor-1')
    expect(String(client.apiRequest.mock.calls[1][0])).toContain('query_identity=gpq1.stable-target')
    expect(String(client.apiRequest.mock.calls[1][0])).toContain('max_points=200')
  })

  it('posts deletion preview and confirmation as one scoped operation', async () => {
    client.apiRequest.mockResolvedValue({})
    const preview = {
      run_id: 'run-1',
      mode: 'SELECTED' as const,
      record_keys: [{
        raw_file_id: 'raw-1',
        global_receive_sequence: 9,
        source_receive_sequence: 3,
        raw_line_number: 12,
      }],
      include_derived_events: true,
    }

    await previewGroundSyslogDelete(preview)
    await submitGroundSyslogDelete({
      preview_token: 'preview-token-with-safe-length',
      explicit_confirmation: true,
      confirmation_text: 'DELETE 2026-07-29',
      include_derived_events: true,
    })

    expect(client.apiRequest).toHaveBeenNthCalledWith(
      1,
      '/api/rail-transit/ground-unattended/syslog-delete-preview',
      {
        method: 'POST',
        body: JSON.stringify({ ...preview, filters: {} }),
      },
    )
    expect(client.apiRequest).toHaveBeenNthCalledWith(
      2,
      '/api/rail-transit/ground-unattended/syslog-delete',
      {
        method: 'POST',
        body: JSON.stringify({
          preview_token: 'preview-token-with-safe-length',
          explicit_confirmation: true,
          confirmation_text: 'DELETE 2026-07-29',
          include_derived_events: true,
        }),
      },
    )
  })

  it('deletes ground run history with explicit confirmation', async () => {
    client.apiRequest.mockResolvedValue({})

    await deleteGroundRunHistory('run-1')

    expect(client.apiRequest).toHaveBeenCalledWith(
      '/api/rail-transit/ground-unattended/runs/run-1',
      {
        method: 'DELETE',
        body: JSON.stringify({ explicit_confirmation: true }),
      },
    )
  })

  it('requests timeline search with exact server pagination', async () => {
    client.apiRequest.mockResolvedValue({})

    await listGroundTimeline(
      '_03',
      'mesh_linkup',
      'run-1',
      { signal: new AbortController().signal },
      3,
      100,
      'AP01',
    )

    const [url, options] = client.apiRequest.mock.calls[0]
    expect(String(url)).toContain('/timeline?')
    expect(String(url)).toContain('train_id=_03')
    expect(String(url)).toContain('event_type=mesh_linkup')
    expect(String(url)).toContain('run_id=run-1')
    expect(String(url)).toContain('query=AP01')
    expect(String(url)).toContain('page=3')
    expect(String(url)).toContain('page_size=100')
    expect(options).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })
  it('serializes radio-control filters without sending empty values', async () => {
    client.apiRequest.mockResolvedValue({})

    await listGroundSyslogRecords({
      event_family: 'CFGMAN',
      cfg_command_source: 'snmp',
      physical_state: '',
      correlation_status: 'CORRELATED',
      correlation_confidence: 'HIGH',
    })
    await listGroundMrRuntimeStatus({
      mr_role: 'CT',
      radio_state: 'DOWN',
      snmp_state: 'RADIO_DOWN',
    })

    const syslogUrl = String(client.apiRequest.mock.calls[0][0])
    expect(syslogUrl).toContain('event_family=CFGMAN')
    expect(syslogUrl).toContain('cfg_command_source=snmp')
    expect(syslogUrl).toContain('correlation_status=CORRELATED')
    expect(syslogUrl).toContain('correlation_confidence=HIGH')
    expect(syslogUrl).not.toContain('physical_state=')
    expect(String(client.apiRequest.mock.calls[1][0])).toContain(
      '/mr-runtime-status?mr_role=CT&radio_state=DOWN&snmp_state=RADIO_DOWN',
    )
  })
})
