import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useOnlineMrStore } from './onlineMr'
import {
  getCurrentOnlineMrSession,
  getOnlineMrPreview,
  getOnlineMrRawTail,
  listOnlineMrCollectors,
  listOnlineMrRawFiles,
} from '../api/onlineMr'
import type { OnlineMrSessionDetail } from '../types/onlineMr'

vi.mock('../api/onlineMr', () => ({
  getCurrentOnlineMrSession: vi.fn(),
  listOnlineMrCollectors: vi.fn(),
  getOnlineMrPreview: vi.fn(),
  listOnlineMrRawFiles: vi.fn(),
  getOnlineMrRawTail: vi.fn(),
}))

const session: OnlineMrSessionDetail = {
  session_id: 'session-1', site_id: 'demo', mr_name: 'MR-01', device_id: 1, device_name: '列车01',
  status: 'COLLECTING', phase: 'COLLECTING', created_at: null, started_at: '2026-07-14 10:00:00', stopped_at: null,
  duration_seconds: 30, duration_minutes: 0.5, controller_task_id: 'task-1', executor_kind: 'LOCAL', agent_id: null,
  has_raw_data: true, has_parsed_data: false, has_package: false, package_name: null, package_reference: null,
  force_stopped: false, finalization_complete: false, stop_reason: null, task_status: 'RUNNING', mapping_state: 'LINKED',
  error_code: null, error_message: null, session_path_reference: 'MR-01/sessions/session-1', connection_summary: {},
  collection_config: {}, enabled_collectors: ['mesh_link'], traffic_summary: {}, file_summary: {}, database_summary: {
    status: 'missing', available: false, compatible: false, size_bytes: 0, modified_at: null,
    schema_version: null, parser_version: null, tables: [], row_counts: {}, available_capabilities: [],
    missing_capabilities: [], missing_tables: [], error_code: 'ONLINE_MR_DATABASE_NOT_FOUND',
    message: '尚未解析', recoverable: true, action: 'parse_session',
  },
  notes_count: 0, latest_metric_time: null, data_integrity: 'unknown',
}

describe('Online MR polling store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getCurrentOnlineMrSession).mockReset().mockResolvedValue(session)
    vi.mocked(listOnlineMrCollectors).mockReset().mockResolvedValue([])
    vi.mocked(getOnlineMrPreview).mockReset().mockResolvedValue({
      session_id: 'session-1', available: true, updated_at: null, message: '', display_context: {}, link: {}, fping: {}, iperf: {},
    })
    vi.mocked(listOnlineMrRawFiles).mockReset().mockResolvedValue([])
    vi.mocked(getOnlineMrRawTail).mockReset().mockResolvedValue({
      success: true, name: 'collector_output', exists: true, lines: ['ok'], message: '', size_bytes: 2, modified_at: null, summary: {},
    })
    vi.stubGlobal('window', { setInterval, clearInterval })
  })

  it('polls active state and raw tail at separate intervals then stops all timers', async () => {
    vi.useFakeTimers()
    window.setInterval = setInterval
    window.clearInterval = clearInterval
    const store = useOnlineMrStore()
    await store.refreshOverview()
    store.startPolling()
    store.setRawExpanded(true)
    await vi.runAllTicks()
    await vi.advanceTimersByTimeAsync(0)

    const initialTailCalls = vi.mocked(getOnlineMrRawTail).mock.calls.length
    await vi.advanceTimersByTimeAsync(2999)
    expect(getOnlineMrRawTail).toHaveBeenCalledTimes(initialTailCalls)
    await vi.advanceTimersByTimeAsync(1)
    expect(getOnlineMrRawTail).toHaveBeenCalledTimes(initialTailCalls + 3)
    const previewCalls = vi.mocked(getOnlineMrPreview).mock.calls.length
    await vi.advanceTimersByTimeAsync(2000)
    expect(getOnlineMrPreview).toHaveBeenCalledTimes(previewCalls + 1)

    const calls = vi.mocked(getOnlineMrRawTail).mock.calls.length
    store.stopPolling()
    await vi.advanceTimersByTimeAsync(5000)
    expect(getOnlineMrRawTail).toHaveBeenCalledTimes(calls)
    vi.useRealTimers()
  })

  it('does not overlap overview requests and reports only after three failures', async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined
    vi.mocked(getCurrentOnlineMrSession).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject }))
    const store = useOnlineMrStore()
    const first = store.refreshOverview()
    void store.refreshOverview()
    expect(getCurrentOnlineMrSession).toHaveBeenCalledOnce()
    rejectRequest?.(new Error('offline'))
    await first
    expect(store.error).toBe('')

    vi.mocked(getCurrentOnlineMrSession).mockRejectedValue(new Error('offline'))
    await store.refreshOverview()
    await store.refreshOverview()
    expect(store.error).toBe('状态刷新失败，请检查主程序服务或当前采集任务。')
  })

  it('clears realtime state when there is no active session and never loads history', async () => {
    const store = useOnlineMrStore()
    await store.refreshOverview()
    expect(store.current?.session_id).toBe('session-1')

    vi.mocked(getCurrentOnlineMrSession).mockResolvedValue(null)
    await store.refreshOverview()

    expect(store.current).toBeNull()
    expect(store.selected).toBeNull()
    expect(store.collectors).toEqual([])
    expect(store.preview).toBeNull()
    expect(store.rawFiles).toEqual([])
  })
})
