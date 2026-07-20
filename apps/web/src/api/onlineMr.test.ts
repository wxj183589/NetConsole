import { describe, expect, it, vi } from 'vitest'

import { queryOnlineMrMetrics, queryOnlineMrSwitchRssiWindows } from './onlineMr'

describe('Online MR analysis API client', () => {
  it('sends time window, paging and downsample parameters to the paged metric endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { series: [], limit: 1000, offset: 500, page_size_per_metric: 500, next_offset: 1000, returned_points: 0, has_more: false } }) })
    vi.stubGlobal('fetch', fetchMock)

    await queryOnlineMrMetrics('session/1', ['rssi', 'ping_rtt'], { startTime: '2026-07-20 10:00:00', endTime: '2026-07-20 11:00:00', limit: 1000, offset: 500, downsample: 'MIN_MAX', bucketSeconds: 5 })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/online-mr/sessions/session%2F1/metric-page?metric_types=rssi%2Cping_rtt&start_time=2026-07-20+10%3A00%3A00&end_time=2026-07-20+11%3A00%3A00&limit=1000&offset=500&downsample=MIN_MAX&bucket_seconds=5')
  })

  it('keeps history and realtime switch RSSI sources explicit', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { items: [], limit: 200, offset: 0, has_more: false } }) })
    vi.stubGlobal('fetch', fetchMock)

    await queryOnlineMrSwitchRssiWindows('session-1', 'realtime', { limit: 200, offset: 0 })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/online-mr/sessions/session-1/switch-rssi-windows?source=realtime&limit=200&offset=0')
  })
})
