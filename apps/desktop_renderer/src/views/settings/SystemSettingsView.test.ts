// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/systemSettings'
import { currentAppLocale } from '../../i18n/runtime'
import type { SystemSettingsSnapshot } from '../../types/systemSettings'
import SystemSettingsView from './SystemSettingsView.vue'

vi.mock('../../api/systemSettings')
vi.mock('../../features', () => ({
  isFeatureEnabled: vi.fn(() => true),
  loadRendererFeatures: vi.fn(),
}))

const settingsBridge = {
  hostType: 'electron' as const,
  getAppInfo: vi.fn(async () => ({ version: '1.4.3', platform: 'win32', isPackaged: false })),
  selectSettingsTool: vi.fn(async () => ({ cancelled: false, path: 'C:\\tools\\Xshell.exe' })),
  selectSettingsDirectory: vi.fn(async () => ({ cancelled: false, path: 'C:\\sessions' })),
  selectSettingsColor: vi.fn(async () => ({ cancelled: false, color: '#2563EB' as const })),
  executeSettingsAction: vi.fn(async () => ({ success: true })),
}
vi.mock('../../platform/runtime', () => ({
  getPlatformAdapter: () => settingsBridge,
  getRuntimeConfig: () => ({ hostType: 'electron', apiBaseUrl: '', apiToken: '' }),
  resolveApiUrl: vi.fn((path: string) => path),
  resolveWebSocketUrl: vi.fn(() => 'ws://127.0.0.1/ws/tasks'),
}))
const confirmAction = vi.hoisted(() => vi.fn())
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: confirmAction }) }))

function snapshot(): SystemSettingsSnapshot {
  const values = {
    theme: 'light' as const, language: 'zh_CN' as const, theme_color: '#0078D4' as const,
    iperf_path: '', fping_path: '', ipop_path: '', terminal_type: 'securecrt' as const,
    terminal_paths: { securecrt: 'C:\\tools\\SecureCRT.exe', xshell: 'C:\\tools\\Xshell.exe', putty: 'C:\\tools\\putty.exe' },
    securecrt_sessions_root: 'C:\\sessions', ssh_port: 22, telnet_port: 23, crt_encoding: 'UTF-8' as const,
  }
  return { version: 'missing', values, defaults: { ...values, terminal_paths: { putty: '', securecrt: '', xshell: '' } }, current_site_name: 'demo', current_site_path: 'C:\\data\\sites\\demo', language_status: 'BLOCKED_ON_GLOBAL_I18N' }
}

const runtimeStatus = () => ({
  edition: 'dev',
  base_profile: 'full',
  active_profile: 'full',
  state: 'normal' as const,
  preview_active: false,
  session_override_active: false,
  local_override_count: 0,
  configuration_available: true,
})
const selfCheckSnapshot = () => ({
  status: 'normal' as const,
  checked_at: '2026-07-24T08:00:00+00:00',
  packaged: true,
  unicode_sample: '宁波地铁1号线 · 中文设备 · 任务已完成',
  items: [{
    check_id: 'backend_executable',
    title: 'Backend 可执行文件',
    status: 'normal' as const,
    message: '正式包 Backend 可执行文件可用。',
    suggestion: '',
  }],
})

class SelfCheckWebSocket {
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    window.setTimeout(() => this.onmessage?.({
      data: JSON.stringify({
        type: 'snapshot',
        payload: { unicode_probe: '宁波地铁1号线 · 任务已完成' },
      }),
    }), 0)
  }

  close(): void {}
}

const siteStorageReload = vi.fn(async () => undefined)
const siteStorageFocus = vi.fn()
const siteStorageRequestSwitch = vi.fn(async () => undefined)
const SiteStoragePanelStub = defineComponent({
  props: { focused: { type: Boolean, default: false } },
  methods: { reload: siteStorageReload, focus: siteStorageFocus, requestSwitch: siteStorageRequestSwitch },
  template: '<section id="site-storage-management" :class="{ \'storage-panel--focused\': focused }" />',
})

async function mounted(): Promise<{ wrapper: VueWrapper; router: ReturnType<typeof createRouter> }> {
  vi.mocked(api.getSystemSettings).mockResolvedValue(snapshot())
  vi.mocked(api.getFeatureRuntimeStatus).mockResolvedValue(runtimeStatus())
  vi.mocked(api.getRuntimeSelfCheck).mockResolvedValue(selfCheckSnapshot())
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings', component: SystemSettingsView }, { path: '/tools', component: defineComponent({ template: '<div>tools</div>' }) }, { path: '/feature-flags', component: defineComponent({ template: '<div>feature delivery</div>' }) }, { path: '/other', component: defineComponent({ template: '<div>other</div>' }) }] })
  await router.push('/settings'); await router.isReady()
  const wrapper = mount(defineComponent({ template: '<RouterView />' }), {
    global: { plugins: [router], stubs: { SiteStoragePanel: SiteStoragePanelStub } },
  })
  await flushPromises()
  return { wrapper, router }
}

async function change(wrapper: VueWrapper, id: string, value: string): Promise<void> {
  const control = wrapper.findComponent(`[data-testid="${id}"]`) as VueWrapper
  control.vm.$emit('update:modelValue', value); control.vm.$emit('change', value); await nextTick()
}

beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('WebSocket', SelfCheckWebSocket); document.documentElement.className = ''; document.documentElement.lang = 'zh-CN'; document.documentElement.style.cssText = ''
  siteStorageReload.mockClear()
  siteStorageFocus.mockClear()
  siteStorageRequestSwitch.mockClear()
  confirmAction.mockResolvedValue(true)
  vi.mocked(api.getFeatureRuntimeStatus).mockResolvedValue(runtimeStatus())
  settingsBridge.selectSettingsTool.mockResolvedValue({ cancelled: false, path: 'C:\\tools\\Xshell.exe' })
  settingsBridge.selectSettingsDirectory.mockResolvedValue({ cancelled: false, path: 'C:\\sessions' })
  settingsBridge.selectSettingsColor.mockResolvedValue({ cancelled: false, color: '#2563EB' })
  settingsBridge.executeSettingsAction.mockResolvedValue({ success: true })
  settingsBridge.getAppInfo.mockResolvedValue({ version: '1.4.3', platform: 'win32', isPackaged: false })
})
afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

describe('SystemSettingsView mounted behavior', () => {
  it('runs the clean-install checks and verifies REST and WebSocket Chinese text', async () => {
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { reportRendererReady: vi.fn() },
    })

    const { wrapper } = await mounted()

    expect(api.getRuntimeSelfCheck).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('正式包环境自检')
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('REST API 中文往返正常')
      expect(wrapper.text()).toContain('任务 WebSocket 中文往返正常')
    })

    await wrapper.find('[data-testid="runtime-self-check"]').trigger('click')
    await flushPromises()
    expect(api.getRuntimeSelfCheck).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('synchronizes the close-to-tray setting through the desktop bridge', async () => {
    const setCloseToTrayEnabled = vi.fn(async (enabled: boolean) => ({ enabled, available: true }))
    let listener: ((state: { enabled: boolean; available: boolean }) => void) | undefined
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: {
        getCloseToTrayState: vi.fn(async () => ({ enabled: true, available: true })),
        setCloseToTrayEnabled,
        onCloseToTrayChanged: vi.fn((next) => {
          listener = next
          return vi.fn()
        }),
      },
    })
    const { wrapper } = await mounted()
    const toggle = wrapper.findComponent('[data-testid="close-to-tray"]') as VueWrapper<any>
    expect(toggle.props('modelValue')).toBe(true)
    toggle.vm.$emit('update:modelValue', false)
    toggle.vm.$emit('change', false)
    await flushPromises()
    expect(setCloseToTrayEnabled).toHaveBeenCalledWith(false)

    listener?.({ enabled: true, available: true })
    await nextTick()
    expect(toggle.props('modelValue')).toBe(true)
    wrapper.unmount()
  })

  it('previews appearance and restores the saved baseline after save failure and route discard', async () => {
    const { wrapper, router } = await mounted()
    await change(wrapper, 'theme', 'dark'); await change(wrapper, 'language', 'en_US')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(currentAppLocale()).toBe('en_US')
    vi.mocked(api.saveSystemSettings).mockRejectedValueOnce(new Error('disk busy'))
    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(currentAppLocale()).toBe('zh_CN')

    await change(wrapper, 'language', 'en_US')
    confirmAction.mockResolvedValueOnce(true)
    await router.push('/other')
    expect(router.currentRoute.value.path).toBe('/other')
    expect(currentAppLocale()).toBe('zh_CN')
    wrapper.unmount()
  })

  it('hides external terminal controls while preserving their values on save', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')

    vi.mocked(api.saveSystemSettings).mockImplementationOnce(async (values) => ({ ...snapshot(), values, version: 'next' }))
    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('外部终端')
    expect(api.saveSystemSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        terminal_type: 'securecrt',
        terminal_paths: { securecrt: 'C:\\tools\\SecureCRT.exe', xshell: 'C:\\tools\\Xshell.exe', putty: 'C:\\tools\\putty.exe' },
        securecrt_sessions_root: 'C:\\sessions',
      }),
      'missing',
    )
    wrapper.unmount()
  })

  it('shows only the read-only version status and opens the single delivery editor', async () => {
    const { wrapper, router } = await mounted()

    expect(wrapper.text()).toContain('当前版本状态')
    expect(wrapper.text()).toContain('开发版')
    expect(wrapper.text()).not.toContain('搜索功能或 ID')
    await wrapper.find('[data-testid="open-feature-delivery"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/feature-flags')
    wrapper.unmount()
  })

  it('clears legacy runtime overrides only after confirmation', async () => {
    vi.mocked(api.getFeatureRuntimeStatus).mockResolvedValueOnce({ ...runtimeStatus(), local_override_count: 3 })
    vi.mocked(api.clearFeatureRuntimeOverrides).mockResolvedValueOnce(runtimeStatus())
    const { wrapper } = await mounted()

    await wrapper.find('[data-testid="clear-runtime-overrides"]').trigger('click')
    await flushPromises()

    expect(confirmAction).toHaveBeenCalledOnce()
    expect(api.clearFeatureRuntimeOverrides).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('本地覆盖')
    wrapper.unmount()
  })

  it('keeps the status card but hides template editing in packaged runtime', async () => {
    vi.mocked(api.getFeatureRuntimeStatus).mockResolvedValueOnce({
      ...runtimeStatus(), edition: 'customer', base_profile: 'customer', active_profile: 'customer', configuration_available: false,
    })
    const { wrapper } = await mounted()

    expect(wrapper.find('#site-storage-management').exists()).toBe(true)
    expect(wrapper.text()).toContain('客户版')
    expect(wrapper.find('[data-testid="open-feature-delivery"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('hides legacy IPOP controls while preserving the compatibility field on save', async () => {
    const legacy = snapshot()
    legacy.values.ipop_path = 'D:\\IPOP\\IPOP.EXE'
    vi.mocked(api.getSystemSettings).mockResolvedValueOnce(legacy)
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')
    vi.mocked(api.saveSystemSettings).mockImplementationOnce(async (values) => ({
      ...legacy,
      values,
      version: 'next',
    }))

    expect(wrapper.find('[data-testid="select-ipop"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="launch-ipop"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('网络测试组件')
    await wrapper.find('[data-testid="save"]').trigger('click')
    await flushPromises()
    expect(api.saveSystemSettings).toHaveBeenCalledWith(
      expect.objectContaining({ ipop_path: 'D:\\IPOP\\IPOP.EXE' }),
      'missing',
    )
    wrapper.unmount()
  })

  it('shows controlled errors for rejected native bridge operations', async () => {
    const { wrapper } = await mounted()
    settingsBridge.selectSettingsColor.mockRejectedValueOnce(new Error('color bridge failed'))
    settingsBridge.executeSettingsAction.mockRejectedValueOnce(new Error('action bridge failed'))

    await wrapper.find('[data-testid="select-color"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('color bridge failed')
    await wrapper.find('[data-testid="open-settings-config"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('action bridge failed')
    wrapper.unmount()
  })

  it('redirects legacy external terminal focus links to the tool collection', async () => {
    const { wrapper, router } = await mounted()

    await router.push({ path: '/settings', query: { section: 'external-terminal' } })
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/tools')
    expect(router.currentRoute.value.query.section).toBe('external-terminal')
    wrapper.unmount()
  })

  it('reloads and refocuses site storage whenever the route focus parameter changes', async () => {
    const { wrapper, router } = await mounted()

    await router.push({ path: '/settings', query: { section: 'site-storage', site_focus: '1' } })
    await flushPromises()
    expect(siteStorageReload).toHaveBeenCalled()
    expect(siteStorageFocus).toHaveBeenCalled()
    expect(wrapper.get('#site-storage-management').classes()).toContain('storage-panel--focused')

    const reloadCalls = siteStorageReload.mock.calls.length
    const focusCalls = siteStorageFocus.mock.calls.length
    await router.push({ path: '/settings', query: { section: 'site-storage', site_focus: '2' } })
    await flushPromises()
    expect(siteStorageReload.mock.calls.length).toBeGreaterThan(reloadCalls)
    expect(siteStorageFocus.mock.calls.length).toBeGreaterThan(focusCalls)

    wrapper.unmount()
  })

  it('forwards a validated tray site switch request to the Site Storage safety flow', async () => {
    const { wrapper, router } = await mounted()

    await router.push({ path: '/settings', query: { tray_site_switch: 'line-12' } })
    await flushPromises()

    expect(siteStorageRequestSwitch).toHaveBeenCalledWith('line-12')
    expect(router.currentRoute.value.query.tray_site_switch).toBeUndefined()
    wrapper.unmount()
  })
})
