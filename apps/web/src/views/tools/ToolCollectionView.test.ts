// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/externalTools'
import type { ExternalToolListResult, ExternalToolView } from '../../types/externalTools'
import ToolCollectionView from './ToolCollectionView.vue'

vi.mock('../../api/externalTools')

const category = {
  id: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
  name: '其他工具',
  sort_order: 10,
  builtin: true,
}

function tool(overrides: Partial<ExternalToolView> = {}): ExternalToolView {
  return {
    id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
    name: 'IPOP',
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
    status: 'AVAILABLE',
    status_message: '可用',
    launch_count: 0,
    last_launched_at: null,
    created_at: '2026-07-30T00:00:00.000Z',
    updated_at: '2026-07-30T00:00:00.000Z',
    ...overrides,
  }
}

async function mounted(list: ExternalToolListResult) {
  vi.mocked(api.listExternalTools).mockResolvedValue(list)
  Object.defineProperty(window, 'netconsoleDesktop', { configurable: true, value: {} })
  const wrapper = mount(ToolCollectionView, {
    global: { plugins: [createPinia(), ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => Reflect.deleteProperty(window, 'netconsoleDesktop'))

describe('ToolCollectionView', () => {
  it('shows a compact empty state with the first-tool action', async () => {
    const wrapper = await mounted({ schema_version: 1, categories: [category], tools: [] })
    expect(wrapper.text()).toContain('尚未添加第三方工具')
    expect(wrapper.text()).toContain('添加第一个工具')
  })

  it('searches name, category and executable name', async () => {
    const wrapper = await mounted({
      schema_version: 1,
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
      schema_version: 1,
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
