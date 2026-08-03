// @vitest-environment happy-dom

import ElementPlus from 'element-plus'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ExternalToolView } from '../../../types/externalTools'
import ExternalToolCard from './ExternalToolCard.vue'

function tool(overrides: Partial<ExternalToolView> = {}): ExternalToolView {
  return {
    id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
    name: 'SecureCRT',
    source_type: 'system_setting',
    source_key: 'securecrt',
    executable_path: 'C:\\Tools\\SecureCRT.exe',
    executable_name: 'SecureCRT.exe',
    arguments: [],
    working_directory: 'C:\\Tools',
    category_id: '5efeea9e-b3e9-44f4-9ba6-f3f6871f2a52',
    category_name: '终端工具',
    favorite: true,
    sort_order: 10,
    icon_mode: 'auto',
    custom_icon_path: null,
    icon_data_url: null,
    launch_privilege: 'normal',
    launch_count: 0,
    administrator_launch_count: 0,
    last_launched_at: null,
    last_launch_mode: null,
    status: 'AVAILABLE',
    status_message: '可用',
    created_at: '2026-07-30T00:00:00.000Z',
    updated_at: '2026-07-30T00:00:00.000Z',
    ...overrides,
  }
}

describe('ExternalToolCard', () => {
  it('offers a one-time administrator launch from the more menu', async () => {
    const wrapper = mount(ExternalToolCard, {
      props: { tool: tool() },
      global: { plugins: [ElementPlus] },
    })
    wrapper.findComponent({ name: 'ElDropdown' }).vm.$emit('command', 'launch-admin')
    expect(wrapper.emitted('launch-admin')?.[0]?.[0]).toMatchObject({ name: 'SecureCRT' })
  })

  it('routes an unavailable system reference to settings instead of relocation', async () => {
    const wrapper = mount(ExternalToolCard, {
      props: {
        tool: tool({
          executable_path: '',
          working_directory: '',
          status: 'INVALID',
          status_message: '请先在工具集 → 外部终端中配置路径',
        }),
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.text()).toContain('配置路径')
    expect(wrapper.text()).not.toContain('重新定位程序')
    await wrapper.findAll('button').find((button) => button.text() === '配置路径')?.trigger('click')
    expect(wrapper.emitted('configure')).toHaveLength(1)
  })
})
