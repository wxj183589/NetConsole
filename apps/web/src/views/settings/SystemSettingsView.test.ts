// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/systemSettings'
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
  selectSettingsTool: vi.fn(async () => ({ cancelled: false, path: 'C:\tools\Xshell.exe' })),
  selectSettingsDirectory: vi.fn(async () => ({ cancelled: false, path: 'C:\sessions' })),
  selectSettingsColor: vi.fn(async () => ({ cancelled: false, color: '#2563EB' as const })),
  executeSettingsAction: vi.fn(async () => ({ success: true })),
}
vi.mock('../../platform/runtime', () => ({ getPlatformAdapter: () => settingsBridge }))

function snapshot(): SystemSettingsSnapshot {
  const values = {
    theme: 'light' as const, language: 'zh_CN' as const, theme_color: '#0078D4' as const,
    iperf_path: '', fping_path: '', ipop_path: '', terminal_type: 'securecrt' as const,
    terminal_paths: { securecrt: 'C:\tools\SecureCRT.exe', xshell: 'C:\tools\Xshell.exe', putty: 'C:\tools\putty.exe' },
    securecrt_sessions_root: 'C:\sessions', ssh_port: 22, telnet_port: 23, crt_encoding: 'UTF-8' as const,
  }
  return { version: 'missing', values, defaults: { ...values, terminal_paths: { putty: '', securecrt: '', xshell: '' } }, current_site_name: 'demo', current_site_path: 'C:\data\sites\demo', language_status: 'BLOCKED_ON_GLOBAL_I18N' }
}

const featureData = { items: [{ feature_id: 'web.agent_management', title: 'Agent', visible: true, enabled: true, client_package: true, internal_only: false }], preview_active: false }

async function mounted(): Promise<{ wrapper: VueWrapper; router: ReturnType<typeof createRouter> }> {
  vi.mocked(api.getSystemSettings).mockResolvedValue(snapshot())
  vi.mocked(api.getFeatureSettings).mockResolvedValue(featureData)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings', component: SystemSettingsView }, { path: '/other', component: defineComponent({ template: '<div>other</div>' }) }] })
  await router.push('/settings'); await router.isReady()
  const wrapper = mount(defineComponent({ template: '<RouterView />' }), { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

async function change(wrapper: VueWrapper, id: string, value: string): Promise<void> {
  const control = wrapper.findComponent(`[data-testid="${id}"]`) as VueWrapper
  control.vm.$emit('update:modelValue', value); control.vm.$emit('change', value); await nextTick()
}

beforeEach(() => {
  vi.clearAllMocks(); document.documentElement.className = ''; document.documentElement.lang = 'zh-CN'; document.documentElement.style.cssText = ''
  vi.mocked(api.getFeatureSettings).mockResolvedValue(featureData)
})

describe('SystemSettingsView mounted behavior', () => {
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
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(undefined as never)
    await router.push('/other')
    expect(router.currentRoute.value.path).toBe('/other')
    expect(currentAppLocale()).toBe('zh_CN')
    wrapper.unmount()
  })

  it('keeps the three terminal paths independent and saves with the current version', async () => {
    const { wrapper } = await mounted()
    const pathInput = () => wrapper.findAllComponents({ name: 'ElInput' })[3]!
    expect(pathInput().props('modelValue')).toBe('C:\tools\SecureCRT.exe')
    await change(wrapper, 'terminal-type', 'xshell')
    expect(pathInput().props('modelValue')).toBe('C:\tools\Xshell.exe')
    pathInput().vm.$emit('update:modelValue', 'D:\Xshell\Xshell.exe'); await nextTick()
    await change(wrapper, 'terminal-type', 'putty')
    expect(pathInput().props('modelValue')).toBe('C:\tools\putty.exe')

    vi.mocked(api.saveSystemSettings).mockImplementationOnce(async (values) => ({ ...snapshot(), values, version: 'next' }))
    await wrapper.find('[data-testid="save"]').trigger('click'); await flushPromises()
    expect(api.saveSystemSettings).toHaveBeenCalledWith(expect.objectContaining({ terminal_paths: { securecrt: 'C:\tools\SecureCRT.exe', xshell: 'D:\Xshell\Xshell.exe', putty: 'C:\tools\putty.exe' } }), 'missing')
    wrapper.unmount()
  })

  it('requires confirmation before feature preview and applies the real preview response', async () => {
    const { wrapper } = await mounted()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(undefined as never)
    vi.mocked(api.previewFeatureSettings).mockResolvedValueOnce({ ...featureData, preview_active: true })
    await wrapper.find('[data-testid="preview-features"]').trigger('click'); await flushPromises()
    expect(api.previewFeatureSettings).toHaveBeenCalledWith(featureData.items)
    expect(wrapper.text()).toContain('客户配置预览中')
    wrapper.unmount()
  })
})
