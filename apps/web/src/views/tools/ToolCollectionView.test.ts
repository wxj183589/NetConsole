// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/externalTools'
import * as settingsApi from '../../api/systemSettings'
import type { ExternalToolListResult, ExternalToolView } from '../../types/externalTools'
import type { SystemSettingsSnapshot } from '../../types/systemSettings'
import ToolCollectionView from './ToolCollectionView.vue'

vi.mock('../../api/externalTools')
vi.mock('../../api/systemSettings')
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
const settingsBridge = {
  selectSettingsTool: vi.fn(async () => ({ cancelled: false, path: 'D:\\PuTTY\\PuTTY64.exe' })),
  selectSettingsDirectory: vi.fn(async () => ({ cancelled: false, path: 'D:\\Sessions' })),
}
vi.mock('../../platform/runtime', () => ({
  getPlatformAdapter: () => settingsBridge,
}))

const category = {
  id: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
  name: '其他工具',
  sort_order: 10,
  builtin: true,
}
const terminalCategory = {
  id: '5efeea9e-b3e9-44f4-9ba6-f3f6871f2a52',
  name: '终端工具',
  sort_order: 20,
  builtin: true,
}

function tool(overrides: Partial<ExternalToolView> = {}): ExternalToolView {
  return {
    id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
    name: 'IPOP',
    source_type: 'independent',
    source_key: null,
    executable_path: 'C:\\Tools\\IPOP.EXE',
    executable_name: 'IPOP.EXE',
    arguments: [],
    working_directory: 'C:\\Tools',
    category_id: category.id,
    category_name: category.name,
    favorite: false,
    sort_order: 10,
    icon_mode: 'auto',
    custom_icon_path: null,
    icon_data_url: null,
    launch_privilege: 'normal',
    status: 'AVAILABLE',
    status_message: '可用',
    launch_count: 0,
    administrator_launch_count: 0,
    last_launched_at: null,
    last_launch_mode: null,
    created_at: '2026-07-30T00:00:00.000Z',
    updated_at: '2026-07-30T00:00:00.000Z',
    ...overrides,
  }
}

function terminalTool(sourceKey: 'securecrt' | 'xshell' | 'putty', executablePath = ''): ExternalToolView {
  const name = sourceKey === 'securecrt' ? 'SecureCRT' : sourceKey === 'xshell' ? 'Xshell' : 'PuTTY'
  const executableName = executablePath ? executablePath.split(/[\\/]/).pop() ?? name : name
  return tool({
    id: `00000000-0000-4000-8000-0000000000${sourceKey === 'securecrt' ? '01' : sourceKey === 'xshell' ? '02' : '03'}`,
    name,
    source_type: 'system_setting',
    source_key: sourceKey,
    executable_path: executablePath,
    executable_name: executableName,
    working_directory: executablePath ? 'C:\\Tools' : '',
    category_id: terminalCategory.id,
    category_name: terminalCategory.name,
    favorite: true,
    status: executablePath ? 'AVAILABLE' : 'INVALID',
    status_message: executablePath ? '可用' : '请先在工具集 → 外部终端中配置路径',
  })
}

function settingsSnapshot(): SystemSettingsSnapshot {
  const values = {
    theme: 'light' as const,
    language: 'zh_CN' as const,
    theme_color: '#0078D4' as const,
    iperf_path: '',
    fping_path: '',
    ipop_path: '',
    terminal_type: 'securecrt' as const,
    terminal_paths: { securecrt: 'C:\\Tools\\SecureCRT.exe', xshell: '', putty: '' },
    securecrt_sessions_root: 'C:\\Sessions',
    ssh_port: 22,
    telnet_port: 23,
    crt_encoding: 'UTF-8' as const,
  }
  return {
    version: 'version-1',
    values,
    defaults: { ...values, terminal_paths: { securecrt: '', xshell: '', putty: '' } },
    current_site_name: 'demo',
    current_site_path: 'D:\\NetConsoleData\\sites\\demo',
    language_status: 'BLOCKED_ON_GLOBAL_I18N',
  }
}

async function mounted(list: ExternalToolListResult) {
  vi.mocked(api.listExternalTools).mockResolvedValue(list)
  vi.mocked(settingsApi.getSystemSettings).mockResolvedValue(settingsSnapshot())
  Object.defineProperty(window, 'netconsoleDesktop', { configurable: true, value: {} })
  const wrapper = mount(ToolCollectionView, {
    global: { plugins: [createPinia(), ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  settingsBridge.selectSettingsTool.mockResolvedValue({ cancelled: false, path: 'D:\\PuTTY\\PuTTY64.exe' })
  settingsBridge.selectSettingsDirectory.mockResolvedValue({ cancelled: false, path: 'D:\\Sessions' })
})
afterEach(() => Reflect.deleteProperty(window, 'netconsoleDesktop'))
afterEach(() => { document.body.innerHTML = '' })

describe('ToolCollectionView', () => {
  it('shows a compact empty state with the first-tool action', async () => {
    const wrapper = await mounted({ schema_version: 2, categories: [category], tools: [] })
    expect(wrapper.text()).toContain('尚未添加第三方工具')
    expect(wrapper.text()).toContain('添加第一个工具')
    expect(wrapper.text()).toContain('外部终端配置')
  })

  it('shows preset terminal cards even when their configured paths are empty', async () => {
    const wrapper = await mounted({
      schema_version: 2,
      categories: [terminalCategory],
      tools: [
        terminalTool('securecrt', 'C:\\Tools\\SecureCRT.exe'),
        terminalTool('xshell'),
        terminalTool('putty'),
      ],
    })
    expect(wrapper.text()).toContain('SecureCRT')
    expect(wrapper.text()).toContain('Xshell')
    expect(wrapper.text()).toContain('PuTTY')
    expect(wrapper.text()).toContain('配置路径')
    expect(api.createExternalToolSystemReference).not.toHaveBeenCalled()
  })

  it('moves external terminal configuration into the tool collection', async () => {
    vi.mocked(settingsApi.saveSystemSettings).mockImplementationOnce(async (values) => ({
      ...settingsSnapshot(),
      values,
      version: 'version-2',
    }))
    const wrapper = await mounted({ schema_version: 2, categories: [terminalCategory], tools: [terminalTool('securecrt'), terminalTool('xshell'), terminalTool('putty')] })

    await wrapper.find('[data-testid="open-terminal-settings"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="select-putty-tool"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已识别为 PuTTY 程序')

    await wrapper.find('[data-testid="save-terminal-settings"]').trigger('click')
    await flushPromises()

    expect(settingsApi.saveSystemSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        terminal_paths: expect.objectContaining({ putty: 'D:\\PuTTY\\PuTTY64.exe' }),
      }),
      'version-1',
    )
  })

  it('creates or reuses a system terminal shortcut before launching from the terminal panel', async () => {
    const securecrt = tool({
      source_type: 'system_setting',
      source_key: 'securecrt',
      name: 'SecureCRT',
      executable_path: 'C:\\Tools\\SecureCRT.exe',
      executable_name: 'SecureCRT.exe',
    })
    vi.mocked(api.launchExternalTool).mockResolvedValueOnce({ success: true, toolId: securecrt.id })
    const wrapper = await mounted({ schema_version: 2, categories: [terminalCategory], tools: [securecrt] })

    await wrapper.find('[data-testid="open-terminal-settings"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="launch-securecrt-tool"]').trigger('click')
    await flushPromises()

    expect(api.createExternalToolSystemReference).not.toHaveBeenCalled()
    expect(api.launchExternalTool).toHaveBeenCalledWith(securecrt.id, 'normal')
  })

  it('searches name, category and executable name', async () => {
    const wrapper = await mounted({
      schema_version: 2,
      categories: [category],
      tools: [tool(), tool({
        id: '718694db-36e8-4a91-909d-ad328e350271',
        name: 'Wireshark',
        executable_path: 'C:\\Tools\\Wireshark.exe',
        executable_name: 'Wireshark.exe',
      })],
    })
    await wrapper.find('input[placeholder*="搜索工具名称"]').setValue('Wireshark.exe')
    expect(wrapper.text()).toContain('Wireshark')
    expect(wrapper.text()).not.toContain('IPOP.EXE')
  })

  it('marks a missing executable and offers relocation without hiding other tools', async () => {
    const wrapper = await mounted({
      schema_version: 2,
      categories: [category],
      tools: [
        tool({ status: 'MISSING', status_message: '程序文件不存在' }),
        tool({ id: '718694db-36e8-4a91-909d-ad328e350271', name: 'PuTTY' }),
      ],
    })
    expect(wrapper.text()).toContain('程序文件不存在')
    expect(wrapper.text()).toContain('重新定位程序')
    expect(wrapper.text()).toContain('PuTTY')
  })
})
