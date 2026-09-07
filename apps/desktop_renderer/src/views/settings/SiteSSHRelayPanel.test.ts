// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/siteStorage'
import SiteSSHRelayPanel from './SiteSSHRelayPanel.vue'

vi.mock('../../api/siteStorage')

const activeSite = { site_id: 'demo', display_name: '演示局点' }

function relay(overrides: Partial<api.SiteSSHRelay> = {}): api.SiteSSHRelay {
  return {
    site_id: 'demo',
    enabled: true,
    host: '10.81.40.10',
    port: 22,
    username: 'jump',
    credential_ref: 'site-ssh-relay-demo',
    revision: 'r1',
    password_configured: true,
    complete: true,
    runtime_status: 'RUNNING',
    runtime_message: 'SSH 中转已连接',
    host_key_status: 'HOST_KEY_AUTO_UPDATED',
    host_key_fingerprint_sha256: 'SHA256:new',
    host_key_updated_at: '2026-09-08T08:00:00+00:00',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getActiveSite).mockResolvedValue(activeSite as never)
  vi.mocked(api.getSiteSSHRelay).mockResolvedValue(relay())
})

afterEach(() => vi.restoreAllMocks())

describe('SiteSSHRelayPanel', () => {
  it('renders the running state and current auto-maintained host key status', async () => {
    const wrapper = mount(SiteSSHRelayPanel, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('已自动更新')
    expect(wrapper.text()).toContain('SHA256:new')
    expect(wrapper.find('.relay-runtime-alert').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows runtime failure from the API instead of claiming the relay is running', async () => {
    vi.mocked(api.getSiteSSHRelay).mockResolvedValue(relay({
      runtime_status: 'JUMP_HOSTKEY_FAILED',
      runtime_message: '跳板机主机密钥自动维护失败，连接未建立。',
      host_key_status: '',
      host_key_fingerprint_sha256: '',
    }))
    const wrapper = mount(SiteSSHRelayPanel, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('主机密钥维护失败')
    expect(wrapper.text()).toContain('跳板机主机密钥自动维护失败')
    expect(wrapper.text()).not.toContain('SSH 中转设置已保存并启动')
    wrapper.unmount()
  })
})
