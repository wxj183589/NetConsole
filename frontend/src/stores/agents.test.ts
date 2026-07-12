import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import type { AgentItem } from '../types/agent'
import { useAgentStore } from './agents'
import { archiveAgent, createAgent, listAgents, probeAgent, setAgentEnabled, updateAgent } from '../api/agents'

vi.mock('../api/agents', () => ({
  listAgents: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  probeAgent: vi.fn(),
  setAgentEnabled: vi.fn(),
  archiveAgent: vi.fn(),
}))

const onlineAgent: AgentItem = {
  agent_id: 'agent-1', name: '车载 Agent', base_url: 'http://127.0.0.1:18080', enabled: true,
  authentication_type: 'token', has_credential: true, tags: ['车载'], note: '测试', created_at: '', updated_at: '',
  status: 'ONLINE', last_seen_at: '', last_checked_at: '', latency_ms: 12, version: 'v1.0.0-windows',
  platform: 'windows', architecture: 'amd64', capabilities: { ping_probe: true }, last_error_code: '', last_error_message: '',
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

describe('Agent store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(listAgents).mockReset().mockResolvedValue([onlineAgent])
    vi.mocked(createAgent).mockReset().mockResolvedValue(onlineAgent)
    vi.mocked(updateAgent).mockReset().mockResolvedValue({ ...onlineAgent, note: '已更新' })
    vi.mocked(probeAgent).mockReset().mockResolvedValue(onlineAgent)
    vi.mocked(setAgentEnabled).mockReset().mockResolvedValue({ ...onlineAgent, enabled: false, status: 'DISABLED' })
    vi.mocked(archiveAgent).mockReset().mockResolvedValue(undefined)
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('window', {
      location: { protocol: 'http:', host: '127.0.0.1:8000' },
      setTimeout,
      clearTimeout,
    })
  })

  it('loads list and filters status, enabled state and search', async () => {
    const store = useAgentStore()
    await store.refresh()
    expect(store.onlineCount).toBe(1)
    expect(store.filtered('车载', 'ONLINE', 'enabled')).toEqual([onlineAgent])
    expect(store.filtered('', 'OFFLINE', '')).toEqual([])
    expect(JSON.stringify(store.agents)).not.toContain('top-secret-token')
  })

  it('supports empty list, create, edit, probe, enable toggle and archive flows', async () => {
    vi.mocked(listAgents).mockResolvedValueOnce([]).mockResolvedValue([onlineAgent])
    const store = useAgentStore()
    await store.refresh()
    expect(store.agents).toEqual([])
    const form = { name: '车载 Agent', base_url: 'http://127.0.0.1:18080', enabled: true, authentication_type: 'none' as const, tags: [], note: '' }
    await store.save(form)
    await store.save({ ...form, note: '已更新' }, 'agent-1')
    await store.probe('agent-1')
    await store.toggle(onlineAgent)
    await store.archive('agent-1')
    expect(createAgent).toHaveBeenCalledOnce()
    expect(updateAgent).toHaveBeenCalledOnce()
    expect(probeAgent).toHaveBeenCalledWith('agent-1')
    expect(setAgentEnabled).toHaveBeenCalledWith('agent-1', false)
    expect(archiveAgent).toHaveBeenCalledWith('agent-1')
  })

  it('uses websocket snapshot and refreshes full list after reconnect', async () => {
    vi.useFakeTimers()
    window.setTimeout = setTimeout
    window.clearTimeout = clearTimeout
    const store = useAgentStore()
    store.connectSocket()
    FakeWebSocket.instances[0].open()
    await vi.runAllTicks()
    FakeWebSocket.instances[0].receive({ type: 'snapshot', agents: [] })
    expect(store.agents).toEqual([])
    FakeWebSocket.instances[0].close()
    await vi.advanceTimersByTimeAsync(2000)
    expect(FakeWebSocket.instances).toHaveLength(2)
    FakeWebSocket.instances[1].open()
    await vi.runAllTicks()
    expect(listAgents).toHaveBeenCalledTimes(2)
    store.disconnectSocket()
    vi.useRealTimers()
  })
})
