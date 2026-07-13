import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useTrafficStore } from './traffic'
import {
  getTrafficRun,
  getTrafficSummary,
  listTrafficEvents,
  listTrafficExecutionTargets,
  listTrafficPingSamples,
  listTrafficRuns,
  startFping,
} from '../api/traffic'
import type { TrafficEvent, TrafficExecutionTarget, TrafficPingSample, TrafficRun } from '../types/traffic'

vi.mock('../api/traffic', () => ({
  listTrafficExecutionTargets: vi.fn(),
  startIperfServer: vi.fn(),
  startIperfClient: vi.fn(),
  startFping: vi.fn(),
  listTrafficRuns: vi.fn(),
  getTrafficRun: vi.fn(),
  getTrafficSummary: vi.fn(),
  listTrafficEvents: vi.fn(),
  listTrafficPingSamples: vi.fn(),
  cancelTrafficRun: vi.fn(),
  retryTrafficRun: vi.fn(),
}))

const localTarget: TrafficExecutionTarget = {
  kind: 'LOCAL',
  id: 'LOCAL',
  display_name: '本机',
  available: true,
  unavailable_reason: '',
  agent_id: '',
  status: '',
  platform: '',
  architecture: '',
  version: '',
  capabilities: { fping: true, iperf_server: true, iperf_client: true },
}

const run: TrafficRun = {
  id: 'run-1',
  traffic_run_id: 'run-1',
  controller_task_id: 'task-1',
  test_type: 'HIGH_FREQUENCY_PING',
  role: 'ping',
  executor_kind: 'LOCAL',
  agent_id: '',
  normalized_config: { targets: ['192.0.2.1'] },
  status: 'RUNNING',
  created_at: '2026-07-13T00:00:00Z',
  started_at: '2026-07-13T00:00:00Z',
  finished_at: '',
  updated_at: '2026-07-13T00:00:01Z',
  summary: { sent: 1 },
  error_code: '',
  error_message: '',
  raw_reference: '',
  result_reference: '',
  retry_of_traffic_run_id: '',
  parent_task_id: '',
  correlation_id: '',
  last_event_sequence: 1,
  sync_state: 'ACTIVE',
  cancellable: true,
}

const event: TrafficEvent = {
  sequence: 1,
  timestamp: '2026-07-13T00:00:01Z',
  traffic_run_id: 'run-1',
  controller_task_id: 'task-1',
  source: 'local',
  type: 'sample',
  payload: { rtt_ms: 1.2 },
  remote_sequence: null,
}

const sample: TrafficPingSample = {
  traffic_run_id: 'run-1',
  sequence: 1,
  timestamp: '2026-07-13T00:00:01Z',
  target: '192.0.2.1',
  probe_sequence: 1,
  ok: true,
  rtt_ms: 1.2,
  timeout: false,
  packet_size: 64,
  error_code: '',
  error_message: '',
}

class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  open(): void { this.readyState = 1; this.onopen?.() }
  receive(value: unknown): void { this.onmessage?.({ data: JSON.stringify(value) }) }
  close(): void { this.readyState = 3; this.onclose?.() }
}

describe('Traffic store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(listTrafficExecutionTargets).mockReset().mockResolvedValue([localTarget])
    vi.mocked(listTrafficRuns).mockReset().mockResolvedValue([run])
    vi.mocked(getTrafficRun).mockReset().mockResolvedValue(run)
    vi.mocked(getTrafficSummary).mockReset().mockResolvedValue({ traffic_run_id: 'run-1', updated_at: run.updated_at, summary: { sent: 1 } })
    vi.mocked(listTrafficEvents).mockReset().mockResolvedValue([event])
    vi.mocked(listTrafficPingSamples).mockReset().mockResolvedValue([sample])
    vi.mocked(startFping).mockReset().mockResolvedValue({ run })
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('window', {
      location: { protocol: 'http:', host: '127.0.0.1:8000' },
      setTimeout,
      clearTimeout,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })
  })

  it('loads targets, runs and starts fping through the traffic API', async () => {
    const store = useTrafficStore()
    await store.refreshTargets()
    await store.refreshRuns()
    expect(store.targets).toEqual([localTarget])
    expect(store.runningCount).toBe(1)

    await store.createFping({
      execution_target: { kind: 'LOCAL' },
      targets: ['192.0.2.1'],
      interval_ms: 100,
      timeout_ms: 100,
      packet_size: 64,
      count: 3,
      continuous: false,
    })

    expect(startFping).toHaveBeenCalledOnce()
    expect(store.selected?.traffic_run_id).toBe('run-1')
  })

  it('connects with REST cursors and merges dedicated incremental samples', async () => {
    const store = useTrafficStore()
    await store.selectRun('run-1')
    expect(FakeWebSocket.instances[0].url).toBe('ws://127.0.0.1:8000/ws/traffic/run-1?after_event=1&after_sample=1')
    FakeWebSocket.instances[0].open()
    FakeWebSocket.instances[0].receive({ type: 'samples', samples: [{ ...sample, sequence: 2, rtt_ms: 2.4 }] })
    FakeWebSocket.instances[0].receive({
      type: 'events',
      events: [{ ...event, sequence: 2, type: 'state', payload: { state: 'COMPLETED' } }],
    })
    expect(store.socketConnected).toBe(true)
    expect(store.samples.map((item) => item.sequence)).toEqual([1, 2])
    expect(store.selected?.status).toBe('COMPLETED')
    store.disconnectSocket()
  })
})
