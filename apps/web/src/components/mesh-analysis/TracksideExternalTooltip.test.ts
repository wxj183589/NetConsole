// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TracksideExternalTooltip from './TracksideExternalTooltip.vue'
import type { TracksideTooltipEntry } from './tracksideTooltip'

const entries: TracksideTooltipEntry[] = [
  {
    apName: 'AP-B',
    radio: 2,
    role: 'STANDBY',
    tracksideRssi: null,
    mrRssi: null,
    station: '站点乙',
    section: null,
    activeDurationSeconds: 12.5,
  },
  {
    apName: 'AP-A',
    radio: 1,
    role: 'ACTIVE',
    tracksideRssi: 29,
    mrRssi: 21,
    station: '站点甲',
    section: '区间甲',
    activeDurationSeconds: 7.574,
  },
]

describe('TracksideExternalTooltip', () => {
  it('renders roles and AP details on separate rows with compact business fields', () => {
    const wrapper = mount(TracksideExternalTooltip, {
      props: {
        visible: true,
        timestamp: '2026-07-20 13:53:19.181',
        entries,
        side: 'right',
      },
    })

    expect(wrapper.findAll('.trackside-tooltip-entry__role').map((item) => item.text())).toEqual([
      '● ACTIVE',
      '○ STANDBY',
    ])
    expect(wrapper.findAll('.trackside-tooltip-entry__ap').map((item) => item.text())).toEqual([
      'AP：AP-A · Radio 1',
      'AP：AP-B · Radio 2',
    ])
    expect(wrapper.text().match(/采样时间：/g)).toHaveLength(1)
    expect(wrapper.text()).toContain('轨旁 / MR RSSI：29 / 21')
    expect(wrapper.text()).toContain('轨旁 / MR RSSI：— / —')
    expect(wrapper.text().match(/主链持续：/g)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('-29')
    expect(wrapper.text()).not.toMatch(/Peer Radio MAC|Peer MAC|数据来源|dBm|series_id|run_id|link_id/i)
    expect(wrapper.classes()).toContain('is-right')
  })

  it('keeps wheel events inside the external tooltip', async () => {
    const wrapper = mount(TracksideExternalTooltip, {
      attachTo: document.body,
      props: { visible: true, entries },
    })
    const parent = wrapper.element.parentElement
    const parentWheel = vi.fn()
    parent?.addEventListener('wheel', parentWheel)

    await wrapper.trigger('wheel')

    expect(parentWheel).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
