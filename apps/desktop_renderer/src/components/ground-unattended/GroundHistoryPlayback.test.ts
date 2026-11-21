// @vitest-environment happy-dom
import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import GroundHistoryPlayback from './GroundHistoryPlayback.vue'

const api = vi.hoisted(() => ({ monitor: vi.fn() }))
vi.mock('../../api/groundUnattended', () => ({ getGroundMrMonitoring: api.monitor }))

describe('Ground history playback isolation', () => {
  it('does not start or query anything merely by entering playback', async () => {
    const wrapper = shallowMount(GroundHistoryPlayback, {
      props: { siteId: 'hzdt-09', runs: [], trains: [], active: true },
      global: { stubs: { ElSelect: true, ElOption: true, ElDatePicker: true, ElButton: true, ElAlert: true, ElPagination: true, MrMonitoringChart: true } },
    })
    await wrapper.vm.$nextTick()
    expect(api.monitor).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('不启动采集')
    wrapper.unmount()
  })
})
