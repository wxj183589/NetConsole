// @vitest-environment happy-dom
import { shallowMount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAppLocale, t } from '../../i18n/runtime'
import SettingsPage from './SettingsPage.vue'

const injected = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => injected.current }))
afterEach(() => setAppLocale('zh_CN'))

describe('Ground settings language switching', () => {
  it('updates empty-state actions and configuration labels without remounting', async () => {
    const profile = ref<Record<string, unknown> | null>(null)
    injected.current = {
      t, profile, profileLoadError: ref(''), loading: ref(false), saving: ref(false),
      pingPresets: ref([]), trains: ref([]), visibleIpv4Addresses: ref([]),
      sourceRecommendation: ref(null), udpPortCheck: ref(null),
    }
    setAppLocale('zh_CN')
    const wrapper = shallowMount(SettingsPage, {
      global: {
        renderStubDefaultSlot: true,
        stubs: {
          ElEmpty: { props: ['description'], template: '<div>{{ description }}<slot /></div>' },
          ElFormItem: { props: ['label'], template: '<div>{{ label }}<slot /></div>' },
          ElOption: { props: ['label'], template: '<div>{{ label }}</div>' },
        },
      },
    })
    expect(wrapper.text()).toContain('重新加载配置')
    setAppLocale('en_US')
    await nextTick()
    expect(wrapper.text()).toContain('Reload configuration')
    expect(wrapper.text()).toContain('Unattended configuration has not loaded')
    expect(wrapper.text()).not.toContain('重新加载配置')

    profile.value = { deep_fping: {}, deep_collection_master_enabled: true, detail_retention_days: 30 }
    await nextTick()
    expect(wrapper.text()).toContain('UDP Syslog and boot checks')
    expect(wrapper.text()).toContain('Local listen address')
    expect(wrapper.text()).toContain('30 days')
    expect(wrapper.text()).toContain('Beijing time (Asia/Shanghai)')
    setAppLocale('zh_CN')
    await nextTick()
    expect(wrapper.text()).toContain('UDP Syslog 与上电检查')
    expect(wrapper.text()).toContain('本机监听地址')
    expect(wrapper.text()).toContain('30 天')
    wrapper.unmount()
  })
})
