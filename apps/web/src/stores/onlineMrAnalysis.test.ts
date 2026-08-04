import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  getOnlineMrSession,
  listRecentOnlineMrSessions,
} from '../api/onlineMr'
import type { OnlineMrSessionDetail, OnlineMrSessionSummary } from '../types/onlineMr'
import { useOnlineMrAnalysisStore } from './onlineMrAnalysis'

vi.mock('../api/onlineMr', () => ({
  getOnlineMrSession: vi.fn(),
  listRecentOnlineMrSessions: vi.fn(),
}))

function summary(sessionId: string, siteId = 'site-a'): OnlineMrSessionSummary {
  return {
    session_id: sessionId,
    site_id: siteId,
    mr_name: `MR-${sessionId}`,
    device_id: sessionId,
    device_name: `MR-${sessionId}`,
    status: 'STOPPED',
    phase: 'TERMINAL',
    created_at: null,
    started_at: null,
    stopped_at: null,
    duration_seconds: 1,
    duration_minutes: 0.001,
    controller_task_id: null,
    executor_kind: 'LOCAL',
    agent_id: null,
    has_raw_data: true,
    has_parsed_data: false,
    has_package: false,
    package_name: null,
    package_reference: null,
    force_stopped: false,
    finalization_complete: true,
    stop_reason: null,
    task_status: 'COMPLETED',
    mapping_state: 'TERMINAL',
    error_code: null,
    error_message: null,
  }
}

function detail(sessionId: string, siteId = 'site-a'): OnlineMrSessionDetail {
  return {
    ...summary(sessionId, siteId),
    session_path_reference: `MR-${sessionId}/sessions/${sessionId}`,
    connection_summary: {},
    collection_config: {},
    enabled_collectors: [],
    traffic_summary: {},
    file_summary: {},
    database_summary: {
      status: 'missing', available: false, compatible: false, size_bytes: 0, modified_at: null,
      schema_version: null, parser_version: null, tables: [], row_counts: {}, available_capabilities: [],
      missing_capabilities: [], missing_tables: [], error_code: null, message: '', recoverable: true, action: null,
    },
    notes_count: 0,
    latest_metric_time: null,
    data_integrity: 'complete',
  }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('Online MR analysis selection store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(listRecentOnlineMrSessions).mockReset()
    vi.mocked(getOnlineMrSession).mockReset()
  })

  it('preserves an existing selection and does not unconditionally select the first row', async () => {
    vi.mocked(listRecentOnlineMrSessions).mockResolvedValue([summary('A'), summary('B')])
    const store = useOnlineMrAnalysisStore()
    await store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: true })
    store.selectSession('B')

    await store.refreshSessions({ siteKey: 'site-a' })
    expect(store.selectedSessionId).toBe('B')

    store.clearSelectedSession()
    await store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: false })
    expect(store.selectedSessionId).toBeNull()
  })

  it('publishes only the latest detail when A, B and C resolve out of order', async () => {
    const requests = new Map<string, ReturnType<typeof deferred<OnlineMrSessionDetail>>>()
    vi.mocked(listRecentOnlineMrSessions).mockResolvedValue([summary('A'), summary('B'), summary('C')])
    vi.mocked(getOnlineMrSession).mockImplementation((sessionId) => {
      const request = deferred<OnlineMrSessionDetail>()
      requests.set(sessionId, request)
      return request.promise
    })
    const store = useOnlineMrAnalysisStore()
    await store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: false })

    store.selectSession('A')
    const a = store.loadSelectedSession('site-a')
    store.selectSession('B')
    const b = store.loadSelectedSession('site-a')
    store.selectSession('C')
    const c = store.loadSelectedSession('site-a')
    requests.get('C')!.resolve(detail('C'))
    await c
    requests.get('B')!.resolve(detail('B'))
    requests.get('A')!.resolve(detail('A'))
    await Promise.all([a, b])

    expect(store.selectedSessionId).toBe('C')
    expect(store.selectedSessionDetail?.session_id).toBe('C')
  })

  it('does not publish a deleted session from a late detail response', async () => {
    const request = deferred<OnlineMrSessionDetail>()
    vi.mocked(listRecentOnlineMrSessions).mockResolvedValue([summary('B')])
    vi.mocked(getOnlineMrSession).mockReturnValue(request.promise)
    const store = useOnlineMrAnalysisStore()
    await store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: true })
    const loading = store.loadSelectedSession('site-a')
    store.removeSessionLocally('B')
    request.resolve(detail('B'))
    await loading

    expect(store.sessions).toEqual([])
    expect(store.selectedSessionDetail).toBeNull()
  })

  it('keeps a tombstoned session out when an older list response contains it', async () => {
    vi.mocked(listRecentOnlineMrSessions).mockResolvedValueOnce([summary('A'), summary('B')])
    const store = useOnlineMrAnalysisStore()
    await store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: true })
    const stale = deferred<OnlineMrSessionSummary[]>()
    vi.mocked(listRecentOnlineMrSessions).mockReturnValueOnce(stale.promise)
    const refreshing = store.refreshSessions({ siteKey: 'site-a' })
    store.removeSessionLocally('B')
    stale.resolve([summary('A'), summary('B')])
    await refreshing

    expect(store.sessions.map((item) => item.session_id)).toEqual(['A'])
    expect(store.isDeleted('B')).toBe(true)
  })

  it('ignores old-site list and detail responses after a site reset', async () => {
    const oldList = deferred<OnlineMrSessionSummary[]>()
    vi.mocked(listRecentOnlineMrSessions).mockReturnValueOnce(oldList.promise)
    const store = useOnlineMrAnalysisStore()
    const loadingOldList = store.refreshSessions({ siteKey: 'site-a', selectFirstWhenEmpty: true })
    store.resetForSite('site-b')
    vi.mocked(listRecentOnlineMrSessions).mockResolvedValueOnce([summary('C', 'site-b')])
    await store.refreshSessions({ siteKey: 'site-b', selectFirstWhenEmpty: true })
    oldList.resolve([summary('A', 'site-a')])
    await loadingOldList

    expect(store.siteKey).toBe('site-b')
    expect(store.sessions.map((item) => item.session_id)).toEqual(['C'])
    expect(store.selectedSessionId).toBe('C')
  })
})
