import { describe, expect, it, vi } from 'vitest'

import {
  cancelWirelessTask,
  deleteWirelessProject,
  exportNetworkTask,
  exportWirelessScan,
  getNetworkProbeEnvironment,
  getNetworkExportArtifact,
  getWirelessExportArtifact,
  getWirelessRunDetail,
  listNetworkTaskResults,
  listWirelessResults,
  listWirelessRuns,
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
    await getNetworkProbeEnvironment()
    await exportNetworkTask('probe-1', 'csv')
    await getNetworkExportArtifact('export-1')
    await listWirelessTasks()
    await listWirelessRuns(21, 50)
    await listWirelessResults('scan_20260715_120000_deadbeef', 22, 100, { only_trackside: true, band: '5G', radio: '2', search: '测试站' })
    await getWirelessRunDetail('scan_20260715_120000_deadbeef')
    await deleteWirelessProject('project-1')
    await cancelWirelessTask('scan-1')
    await exportWirelessScan('scan_20260715_120000_deadbeef', 'xlsx')
    await getWirelessExportArtifact('wireless-export-1')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/network-tools/runs/probe-1/results?offset=100&limit=50',
      '/api/network-tools/toolbox/probe-environment',
      '/api/network-tools/runs/probe-1/export',
      '/api/network-tools/runs/export-1/artifact',
      '/api/network-tools/wireless-scan/tasks?limit=200',
      '/api/network-tools/wireless-scan/runs?page=21&page_size=50',
      '/api/network-tools/wireless-scan/runs/scan_20260715_120000_deadbeef/results?page=22&page_size=100&only_trackside=true&band=5G&radio=2&search=%E6%B5%8B%E8%AF%95%E7%AB%99',
      '/api/network-tools/wireless-scan/runs/scan_20260715_120000_deadbeef',
      '/api/network-tools/wireless-scan/projects/project-1',
      '/api/network-tools/wireless-scan/tasks/scan-1/cancel',
      '/api/network-tools/wireless-scan/export',
      '/api/network-tools/wireless-scan/tasks/wireless-export-1/artifact',
    ])
    expect(fetchMock.mock.calls[2][1].method).toBe('POST')
    expect(fetchMock.mock.calls[8][1].method).toBe('DELETE')
    expect(fetchMock.mock.calls[9][1].method).toBe('POST')
    expect(fetchMock.mock.calls[10][1].method).toBe('POST')
  })
})
