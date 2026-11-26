// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { closeTerminalSession, type TerminalSession } from '../../api/terminal'
import source from './ConsoleWorkspaceView.vue?raw'
import { useConsoleWorkspace } from './useConsoleWorkspace'
import workspaceSource from './useConsoleWorkspace.ts?raw'

vi.mock('../../api/deviceManagement', () => ({ listDevices: vi.fn(async () => ({ items: [] })) }))
vi.mock('../../api/terminal', () => ({
  closeTerminalSession: vi.fn(),
  listTerminalSessions: vi.fn(async () => ({ items: [] })),
  listTerminalHistory: vi.fn(async () => ({ items: [] })),
  listTerminalProfiles: vi.fn(async () => ({ profiles: [], folders: [] })),
  getTerminalSettings: vi.fn(async () => null),
  getTerminalHighlightRules: vi.fn(async () => []),
}))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() }, ElMessageBox: {} }))

let wrapper: VueWrapper | undefined
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.clearAllMocks()
})

async function mountWorkspace() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ name: 'device-console', path: '/console', component: { render: () => null } }] })
  await router.push('/console')
  let workspace!: ReturnType<typeof useConsoleWorkspace>
  wrapper = mount(defineComponent({
    setup() {
      workspace = useConsoleWorkspace()
      return () => h('div')
    },
  }), { global: { plugins: [router] } })
  await flushPromises()
  return workspace
}

function session(id: string, state: TerminalSession['state'] = 'CONNECTED'): TerminalSession {
  return { session_id: id, state } as TerminalSession
}

describe('ConsoleWorkspaceView responsive toolbar', () => {
  it('keeps all terminal actions reachable at the minimum desktop width', () => {
    expect(source).toContain('overflow-x: auto;')
    expect(source).toContain('.terminal-search { flex: 0 0 150px;')
  })

  it('opens a registered device passed from device management exactly once', () => {
    expect(workspaceSource).toContain("query.device_uuid")
    expect(workspaceSource).toContain("router.replace({ name: 'device-console'")
    expect(workspaceSource).toContain('if (requestedDevice) await openDevice(requestedDevice)')
  })
})

describe('Console workspace sessions', () => {
  it('keeps the selected pane visible while closing a background tab', async () => {
    const workspace = await mountWorkspace()
    for (const id of ['first', 'background', 'focused']) workspace.addTerminalTab({ session: session(id), ticket: id })
    vi.mocked(closeTerminalSession).mockResolvedValueOnce(session('background', 'CLOSED'))

    await workspace.closeTab('background')

    expect(workspace.tabs.value.map(tab => tab.id)).toEqual(['first', 'focused'])
    expect(workspace.activeTabId.value).toBe('focused')
    expect([...workspace.visibleTabIds.value]).toEqual(['focused'])
  })

  it('focuses either split pane without swapping its position', async () => {
    const workspace = await mountWorkspace()
    for (const id of ['one', 'two']) workspace.addTerminalTab({ session: session(id), ticket: id })
    workspace.setSplit('horizontal')
    workspace.selectTab('one')

    expect(workspace.paneClass('one')).toContain('is-secondary')
    expect(workspace.paneClass('one')).toContain('is-focused')
    expect(workspace.paneClass('two')).toContain('is-primary')

    workspace.updateSession('two', session('two', 'CLOSED'))
    expect(workspace.splitOrientation.value).toBe('none')
    expect([...workspace.visibleTabIds.value]).toEqual(['one'])
  })

  it('blocks duplicate closes until the backend reports a final state and retains unexpected disconnects', async () => {
    const workspace = await mountWorkspace()
    workspace.addTerminalTab({ session: session('closing'), ticket: 'a' })
    workspace.addTerminalTab({ session: session('network'), ticket: 'b' })
    vi.mocked(closeTerminalSession).mockResolvedValueOnce(session('closing', 'CLOSING'))

    await Promise.all([workspace.closeTab('closing'), workspace.closeTab('closing')])
    expect(closeTerminalSession).toHaveBeenCalledTimes(1)
    expect(workspace.closingTabIds.value.has('closing')).toBe(true)
    expect(workspace.tabs.value.map(tab => tab.id)).toEqual(['closing', 'network'])

    workspace.updateSession('closing', session('closing', 'CLOSED'))
    workspace.updateSession('network', session('network', 'DISCONNECTED'))
    expect(workspace.closingTabIds.value.size).toBe(0)
    expect(workspace.tabs.value.map(tab => tab.session.state)).toEqual(['DISCONNECTED'])
  })
})
