// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/systemSettings'
import { loadWebFeatures } from '../../features'
import { currentAppLocale } from '../../i18n/runtime'
import type { SystemSettingsSnapshot } from '../../types/systemSettings'
import SystemSettingsView from './SystemSettingsView.vue'

vi.mock('../../api/systemSettings')
vi.mock('../../features', () => ({
  isFeatureEnabled: vi.fn(() => true),
  loadWebFeatures: vi.fn(),
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

const featureData = {
  items: [{
    feature_id: 'web.agent_management', title: 'Agent 管理', group_id: 'tasks', group_title: '任务与 Agent', scope: 'global' as const,
    visible: true, enabled: true, inherited_visible: true, inherited_enabled: true,
    client_package: true, internal_only: false, package_range: 'customer_internal' as const, status: 'ENABLED' as const,
    dependencies: [], locked: false, lock_reason: '', overridden: false,
  }],
  preview_active: false,
  configuration_name: '当前实例运行配置',
  scope_label: '全局',
  inherited_profile: 'full',
}
const featureSnapshot = () => ({ ...featureData, items: featureData.items.map((item) => ({ ...item })) })
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
  vi.mocked(api.getFeatureSettings).mockResolvedValue(featureSnapshot())
  vi.mocked(api.getRuntimeSelfCheck).mockResolvedValue(selfCheckSnapshot())
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings', component: SystemSettingsView }, { path: '/other', component: defineComponent({ template: '<div>other</div>' }) }] })
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

async function changeFeatureMode(wrapper: VueWrapper, value: 'enabled_visible' | 'enabled_hidden' | 'disabled'): Promise<void> {
  const control = wrapper.findComponent('[data-testid="feature-mode-web.agent_management"]') as VueWrapper
  control.vm.$emit('change', value)
  await nextTick()
}

beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('WebSocket', SelfCheckWebSocket); document.documentElement.className = ''; document.documentElement.lang = 'zh-CN'; document.documentElement.style.cssText = ''
  siteStorageReload.mockClear()
  siteStorageFocus.mockClear()
  siteStorageRequestSwitch.mockClear()
  confirmAction.mockResolvedValue(true)
  vi.mocked(api.getFeatureSettings).mockResolvedValue(featureSnapshot())
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

  it('keeps the three terminal paths independent and saves with the current version', async () => {
    const { wrapper } = await mounted()
    const pathInput = () => wrapper.findAllComponents({ name: 'ElInput' })[2]!
    expect(pathInput().props('modelValue')).toBe('C:\\tools\\SecureCRT.exe')
    await change(wrapper, 'terminal-type', 'xshell')
    expect(pathInput().props('modelValue')).toBe('C:\\tools\\Xshell.exe')
    pathInput().vm.$emit('update:modelValue', 'D:\\Xshell\\Xshell.exe'); await nextTick()
    await change(wrapper, 'terminal-type', 'putty')
    expect(pathInput().props('modelValue')).toBe('C:\\tools\\putty.exe')

    vi.mocked(api.saveSystemSettings).mockImplementationOnce(async (values) => ({ ...snapshot(), values, version: 'next' }))
    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()
    expect(api.saveSystemSettings).toHaveBeenCalledWith(expect.objectContaining({ terminal_paths: { securecrt: 'C:\\tools\\SecureCRT.exe', xshell: 'D:\\Xshell\\Xshell.exe', putty: 'C:\\tools\\putty.exe' } }), 'missing')
    wrapper.unmount()
  })

  it('accepts PuTTY64.exe and shows field-level executable feedback', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'terminal-type', 'putty')
    settingsBridge.selectSettingsTool.mockResolvedValueOnce({ cancelled: false, path: 'D:\\PuTTY\\PuTTY64.exe' })

    await wrapper.find('[data-testid="select-terminal-tool"]').trigger('click'); await flushPromises()

    const pathInput = wrapper.findAllComponents({ name: 'ElInput' })[2]!
    expect(pathInput.props('modelValue')).toBe('D:\\PuTTY\\PuTTY64.exe')
    expect(wrapper.text()).toContain('已识别为 PuTTY 程序')
    expect(wrapper.text()).not.toContain('所选程序与 PuTTY 类型不匹配')
    wrapper.unmount()
  })

  it('blocks save and keeps a PuTTY executable mismatch beside the field', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'terminal-type', 'putty')
    const field = wrapper.findAllComponents({ name: 'NcExecutablePathField' })[2]!

    field.vm.$emit('update:modelValue', 'D:\\PuTTY\\plink.exe'); await nextTick()

    expect(wrapper.text()).toContain('所选程序与 PuTTY 类型不匹配。请选择 putty.exe 或 putty64.exe。')
    expect(wrapper.find('[data-testid="save"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('shows a non-mutating change preview with read-only release metadata', async () => {
    const { wrapper } = await mounted()
    await changeFeatureMode(wrapper, 'enabled_hidden')
    await wrapper.find('[data-testid="preview-features"]').trigger('click'); await flushPromises()
    expect(api.previewFeatureSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('变更预览')
    expect(wrapper.text()).toContain('显示并启用 → 隐藏入口')
    expect(wrapper.text()).toContain('客户包、内部包')
    expect(wrapper.find('[data-testid="feature-visible-web.agent_management"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not persist either stage when combined changes are not confirmed', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')
    await changeFeatureMode(wrapper, 'disabled')
    confirmAction.mockResolvedValueOnce(false)

    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()

    expect(api.saveFeatureSettings).not.toHaveBeenCalled()
    expect(api.saveSystemSettings).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not save normal settings when the feature stage fails', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')
    await changeFeatureMode(wrapper, 'disabled')
    confirmAction.mockResolvedValueOnce(true)
    vi.mocked(api.saveFeatureSettings).mockRejectedValueOnce(new Error('profile write failed'))

    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()

    expect(api.saveSystemSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('profile write failed')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    wrapper.unmount()
  })

  it('refreshes the effective feature gate and reports a later settings failure as partial success', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')
    await changeFeatureMode(wrapper, 'disabled')
    confirmAction.mockResolvedValueOnce(true)
    vi.mocked(api.saveFeatureSettings).mockResolvedValueOnce({ ...featureData, items: [{ ...featureData.items[0]!, visible: false }] })
    vi.mocked(api.saveSystemSettings).mockRejectedValueOnce(new Error('settings conflict'))

    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()

    expect(loadWebFeatures).toHaveBeenCalledWith(true)
    expect(vi.mocked(api.saveFeatureSettings).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(api.saveSystemSettings).mock.invocationCallOrder[0]!)
    expect(wrapper.text()).toContain('功能开关已保存，但系统设置保存失败')
    wrapper.unmount()
  })

  it('stops before settings save and reports the exact stage when Gate refresh fails', async () => {
    const { wrapper } = await mounted()
    await change(wrapper, 'theme', 'dark')
    await changeFeatureMode(wrapper, 'disabled')
    confirmAction.mockResolvedValueOnce(true)
    vi.mocked(api.saveFeatureSettings).mockResolvedValueOnce({ ...featureData, items: [{ ...featureData.items[0]!, visible: false }] })
    vi.mocked(loadWebFeatures).mockRejectedValueOnce(new Error('gate refresh failed'))

    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()

    expect(api.saveFeatureSettings).toHaveBeenCalledOnce()
    expect(api.saveSystemSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('功能开关已保存，但 Gate/导航刷新失败，系统设置未保存')
    wrapper.unmount()
  })

  it('keeps system settings reload successful when feature loading fails', async () => {
    const { wrapper } = await mounted()
    const success = vi.spyOn(ElMessage, 'success')
    vi.mocked(api.reloadSystemSettings).mockResolvedValueOnce(snapshot())
    vi.mocked(api.getFeatureSettings).mockRejectedValueOnce(new Error('feature load failed'))

    await wrapper.find('[data-testid="reload"]').trigger('click'); await flushPromises()

    expect(wrapper.text()).toContain('feature load failed')
    expect(success).toHaveBeenCalledWith('系统设置已重载')
    wrapper.unmount()
  })

  it('keeps site storage but never requests feature configuration in a packaged runtime', async () => {
    settingsBridge.getAppInfo.mockResolvedValueOnce({ version: '1.4.3', platform: 'win32', isPackaged: true })

    const { wrapper } = await mounted()

    expect(wrapper.find('#site-storage-management').exists()).toBe(true)
    expect(wrapper.find('[data-testid="preview-features"]').exists()).toBe(false)
    expect(api.getFeatureSettings).not.toHaveBeenCalled()
    expect(api.previewFeatureSettings).not.toHaveBeenCalled()
    expect(api.restoreFeatureSettings).not.toHaveBeenCalled()
    expect(api.saveFeatureSettings).not.toHaveBeenCalled()
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
    expect(wrapper.text()).toContain('网络测试组件')
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
    settingsBridge.selectSettingsTool.mockRejectedValueOnce(new Error('tool bridge failed'))
    settingsBridge.selectSettingsDirectory.mockRejectedValueOnce(new Error('directory bridge failed'))
    settingsBridge.selectSettingsColor.mockRejectedValueOnce(new Error('color bridge failed'))
    settingsBridge.executeSettingsAction.mockRejectedValueOnce(new Error('action bridge failed'))

    await wrapper.find('[data-testid="select-terminal-tool"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('tool bridge failed')
    await wrapper.find('[data-testid="select-sessions"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('directory bridge failed')
    await wrapper.find('[data-testid="select-color"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('color bridge failed')
    await wrapper.find('[data-testid="open-settings-config"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('action bridge failed')
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
