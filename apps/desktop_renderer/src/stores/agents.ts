import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { archiveAgent, createAgent, listAgents, probeAgent, setAgentEnabled, updateAgent } from '../api/agents'
import type { AgentFormValue, AgentItem, AgentSocketEvent, AgentStatus } from '../types/agent'
import { resolveWebSocketUrl } from '../platform/runtime'

export const useAgentStore = defineStore('agents', () => {
  const agents = ref<AgentItem[]>([])
  const loading = ref(false)
  const error = ref('')
  const socketConnected = ref(false)
  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null
  let reconnectEnabled = true

  const onlineCount = computed(() => agents.value.filter((agent) => agent.status === 'ONLINE').length)
  const attentionCount = computed(() => agents.value.filter((agent) => ['OFFLINE', 'UNAUTHORIZED'].includes(agent.status)).length)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      agents.value = await listAgents()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'Agent 列表加载失败'
    } finally {
      loading.value = false
    }
  }

  async function save(value: AgentFormValue, agentId = ''): Promise<AgentItem> {
    const item = agentId ? await updateAgent(agentId, value) : await createAgent(value)
    await refresh()
    return item
  }

  async function probe(agentId: string): Promise<AgentItem> {
    try {
      return await probeAgent(agentId)
    } finally {
      await refresh()
    }
  }

  async function toggle(agent: AgentItem): Promise<void> {
    await setAgentEnabled(agent.agent_id, !agent.enabled)
    await refresh()
  }

  async function archive(agentId: string): Promise<void> {
    await archiveAgent(agentId)
    await refresh()
  }

  function filtered(search: string, status: AgentStatus | '', enabled: '' | 'enabled' | 'disabled'): AgentItem[] {
    const keyword = search.trim().toLocaleLowerCase()
    return agents.value.filter((agent) => {
      const matchesSearch = !keyword || [agent.name, agent.base_url, agent.note, ...agent.tags].join(' ').toLocaleLowerCase().includes(keyword)
      const matchesStatus = !status || agent.status === status
      const matchesEnabled = !enabled || (enabled === 'enabled' ? agent.enabled : !agent.enabled)
      return matchesSearch && matchesStatus && matchesEnabled
    })
  }

  function connectSocket(): void {
    if (socket && socket.readyState <= WebSocket.OPEN) return
    reconnectEnabled = true
    socket = new WebSocket(resolveWebSocketUrl('/ws/agents'))
    socket.onopen = () => {
      socketConnected.value = true
      void refresh()
    }
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as AgentSocketEvent
      if (event.type === 'snapshot' && event.agents) {
        agents.value = event.agents
      } else if (event.type !== 'heartbeat') {
        void refresh()
      }
    }
    socket.onclose = () => {
      socketConnected.value = false
      socket = null
      if (reconnectEnabled) reconnectTimer = window.setTimeout(connectSocket, 2000)
    }
    socket.onerror = () => socket?.close()
  }

  function disconnectSocket(): void {
    reconnectEnabled = false
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
    socket?.close()
    socket = null
  }

  return { agents, loading, error, socketConnected, onlineCount, attentionCount, refresh, save, probe, toggle, archive, filtered, connectSocket, disconnectSocket }
})
