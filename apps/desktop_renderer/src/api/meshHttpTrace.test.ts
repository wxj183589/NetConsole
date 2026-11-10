import { beforeEach, describe, expect, it } from 'vitest'
import {
  beginMeshHttpTrace,
  clearMeshHttpTrace,
  completeMeshHttpTrace,
  failMeshHttpTrace,
  getMeshHttpTraceSnapshot,
  recordMeshHttpPayload,
} from './meshHttpTrace'

describe('MESH request-level HTTP trace', () => {
  beforeEach(() => clearMeshHttpTrace())

  it('records real path parameters, request id, query ranges and payload counts', () => {
    const handle = beginMeshHttpTrace(
      '/api/rail-transit/mesh-analysis/sessions/mr%3A1%3A1/links?time_from=2026-11-10%2010%3A00%3A00.000&time_to=2026-11-10%2010%3A01%3A00.000&mesh_operation_id=mesh-op-1',
      'GET',
      1,
    )
    completeMeshHttpTrace(handle, new Response('{}', { status: 200, headers: { 'X-Request-ID': 'request-1' } }))
    recordMeshHttpPayload(handle, {
      items: [{ record_id: 1 }],
      _query_trace: {
        query_kind: 'raw_samples',
        query_id: 'query-1',
        sql_query_count: 3,
        sql_query_ranges: [{ purpose: 'target_rows', time_from: '2026-11-10 10:00:00.000', time_to: '2026-11-10 10:01:00.000', visible: true, record_count: 1 }],
      },
    })
    const event = getMeshHttpTraceSnapshot().events[0]!
    expect(event.path).toContain('/sessions/mr%3A1%3A1/links')
    expect(event.query_params.time_from).toBe('2026-11-10 10:00:00.000')
    expect(event.operation_id).toBe('mesh-op-1')
    expect(event.request_id).toBe('request-1')
    expect(event.query_kind).toBe('raw_samples')
    expect(event.query_id).toBe('query-1')
    expect(event.sql_query_count).toBe(3)
    expect(event.sql_query_ranges).toHaveLength(1)
    expect(event.item_count).toBe(1)
    expect(getMeshHttpTraceSnapshot().active_count).toBe(0)
  })

  it('records aborted requests separately from completed requests', () => {
    const handle = beginMeshHttpTrace('/api/rail-transit/mesh-analysis/summary', 'GET', 1)
    failMeshHttpTrace(handle, Object.assign(new Error('aborted'), { name: 'AbortError' }))
    expect(getMeshHttpTraceSnapshot().events[0]).toMatchObject({ status: 0, cancelled: true, failure: 'aborted' })
    expect(getMeshHttpTraceSnapshot().active_count).toBe(0)
  })

  it('ignores non-MESH requests', () => {
    expect(beginMeshHttpTrace('/api/health', 'GET', 1)).toBeNull()
    expect(getMeshHttpTraceSnapshot().events).toHaveLength(0)
  })
})
