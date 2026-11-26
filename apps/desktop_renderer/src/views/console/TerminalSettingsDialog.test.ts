// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { TerminalHighlightRule, TerminalSettings } from '../../api/terminal'
import TerminalSettingsDialog from './TerminalSettingsDialog.vue'

const mocks = vi.hoisted(() => ({
  settings: vi.fn(), highlights: vi.fn(), dangerous: vi.fn(), update: vi.fn(),
  messageError: vi.fn(), messageSuccess: vi.fn(),
}))

vi.mock('../../api/terminal', () => ({
  getTerminalSettings: mocks.settings,
  getTerminalHighlightRules: mocks.highlights,
  getTerminalDangerousRules: mocks.dangerous,
  updateTerminalSettings: mocks.update,
  previewTerminalRulesImport: vi.fn(),
  replaceTerminalHighlightRules: vi.fn(),
  replaceTerminalDangerousRules: vi.fn(),
}))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: vi.fn() }))
vi.mock('element-plus', async original => ({
  ...await original<object>(),
  ElMessage: { error: mocks.messageError, success: mocks.messageSuccess },
}))

const settings: TerminalSettings = {
  schema_version: 1,
  font_family: 'Consolas', font_size: 14,
  foreground: '#ffffff', background: '#000000', cursor_color: '#ffffff',
  encoding: 'utf-8', automatic_recording: true, automatic_log_retention_days: 30,
  automatic_log_max_bytes: 1048576, manual_log_recent_directory: '', dangerous_command_warning: true,
}
const wrappers: ReturnType<typeof mount>[] = []

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.clearAllMocks()
})

async function mountDialog(props: { initialSettings?: TerminalSettings | null; initialHighlights?: TerminalHighlightRule[] } = {}) {
  const wrapper = mount(TerminalSettingsDialog, {
    props: { modelValue: false, ...props },
    global: { stubs: {
      ElDialog: { template: '<div class="dialog"><slot /><slot name="footer" /></div>' },
      ElTabs: { props: ['modelValue'], emits: ['tab-change'], template: '<div><button class="dangerous-tab" @click="$emit(\'tab-change\', \'dangerous\')">高危命令</button><slot /></div>' },
      ElTabPane: { template: '<div><slot /></div>' },
      ElForm: true, ElFormItem: true, ElSelect: true, ElOption: true, ElInputNumber: true,
      ElColorPicker: true, ElAlert: true, ElButton: true, ElTable: true, ElTableColumn: true,
      ElSwitch: true,
    } },
  })
  wrappers.push(wrapper)
  await wrapper.setProps({ modelValue: true })
  await vi.waitFor(() => {
    expect(wrapper.find('.settings-form').exists() || wrapper.text().includes('终端设置未能加载')).toBe(true)
  })
  return wrapper
}

describe('terminal settings loading', () => {
  it('renders cached settings without loading rule tables and fetches dangerous rules on demand', async () => {
    mocks.dangerous.mockResolvedValue({ rules: [{ id: 'danger-1' }] })
    const wrapper = await mountDialog({ initialSettings: settings, initialHighlights: [] })
    await flushPromises()

    expect(wrapper.get('.dialog').attributes('title')).toBe('终端设置')
    expect(wrapper.find('.terminal-settings-load-state').exists()).toBe(false)
    expect(wrapper.find('.terminal-settings-load-error').exists()).toBe(false)
    expect(mocks.settings).not.toHaveBeenCalled()
    expect(mocks.highlights).not.toHaveBeenCalled()
    expect(mocks.dangerous).not.toHaveBeenCalled()

    await wrapper.get('.dangerous-tab').trigger('click')
    await flushPromises()
    expect(mocks.dangerous).toHaveBeenCalledOnce()
    expect(wrapper.find('.terminal-rules-loading').exists()).toBe(false)
    expect(mocks.messageError).not.toHaveBeenCalled()
  })

  it('shows a concrete error and retries a failed settings request', async () => {
    mocks.settings.mockRejectedValueOnce(new Error('设置服务暂不可用')).mockResolvedValueOnce(settings)
    const wrapper = await mountDialog()
    await flushPromises()
    expect(wrapper.get('.terminal-settings-load-error').text()).toContain('终端设置未能加载')

    await wrapper.get('.terminal-settings-load-error').findComponent({ name: 'ElButton' }).trigger('click')
    await flushPromises()
    expect(mocks.settings).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.terminal-settings-load-error').exists()).toBe(false)
    expect(wrapper.find('.settings-form').exists()).toBe(true)
  })
})
