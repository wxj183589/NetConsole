// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

import { reportApiPerformance, reportTableRenderPerformance } from './performanceProfiling'

afterEach(() => vi.restoreAllMocks())

describe('performance profiling', () => {
  it('reports bounded API metadata without response payloads', () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    reportApiPerformance({
      path: '/api/devices?page=1',
      method: 'GET',
      totalMs: 12.345,
      requestId: 'request-1',
      serverTiming: 'app;dur=10.00, sql;dur=2.00;desc="3 queries"',
    })
    expect(info).toHaveBeenCalledWith('API_PERFORMANCE_PROFILE', {
      path: '/api/devices?page=1',
      method: 'GET',
      total_ms: 12.35,
      request_id: 'request-1',
      server_timing: 'app;dur=10.00, sql;dur=2.00;desc="3 queries"',
    })
  })

  it('reports table DOM commit after the next animation frame', async () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(performance.now())
      return 1
    })
    await reportTableRenderPerformance('ac-fit-ap-resources', 200, performance.now())
    expect(info).toHaveBeenCalledWith('UI_TABLE_PROFILE', expect.objectContaining({
      table_id: 'ac-fit-ap-resources',
      row_count: 200,
    }))
  })
})
