import { describe, expect, it, vi } from 'vitest'

import {
  cancelWirelessTask,
  exportNetworkTask,
  exportWirelessScan,
  getNetworkExportArtifact,
  getWirelessExportArtifact,
  listNetworkTaskResults,
  listWirelessTasks,
  startTcpPortTest,
} from './networkTools'

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

  it('uses recoverable task and scoped artifact endpoints for toolbox and wireless exports', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task: { id: 'task-1' } }) })
    vi.stubGlobal('fetch', fetchMock)

    await listNetworkTaskResults('probe-1', 100, 50)
    await exportNetworkTask('probe-1', 'csv')
    await getNetworkExportArtifact('export-1')
    await listWirelessTasks()
    await cancelWirelessTask('scan-1')
    await exportWirelessScan('scan_20260715_120000_deadbeef', 'xlsx')
    await getWirelessExportArtifact('wireless-export-1')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/network-tools/runs/probe-1/results?offset=100&limit=50',
      '/api/network-tools/runs/probe-1/export',
      '/api/network-tools/runs/export-1/artifact',
      '/api/network-tools/wireless-scan/tasks?limit=200',
      '/api/network-tools/wireless-scan/tasks/scan-1/cancel',
      '/api/network-tools/wireless-scan/export',
      '/api/network-tools/wireless-scan/tasks/wireless-export-1/artifact',
    ])
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
    expect(fetchMock.mock.calls[4][1].method).toBe('POST')
    expect(fetchMock.mock.calls[5][1].method).toBe('POST')
  })
})
