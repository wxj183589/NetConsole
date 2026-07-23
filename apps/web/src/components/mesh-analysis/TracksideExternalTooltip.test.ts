// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TracksideExternalTooltip from './TracksideExternalTooltip.vue'
import type { TracksideTooltipEntry } from './tracksideTooltip'

const entries: TracksideTooltipEntry[] = [
  {
    seriesId: 'series-b',
    metaId: 2,
    apName: 'AP-B',
    radio: 2,
    role: 'STANDBY',
    tracksideRssi: null,
    mrRssi: null,
    station: '站点乙',
    section: null,
    activeDurationSeconds: 12.5,
    color: '#27ae60',
  },
  {
    seriesId: 'series-a',
    metaId: 1,
    apName: 'AP-A',
    radio: 1,
    role: 'ACTIVE',
    tracksideRssi: 29,
    mrRssi: 21,
    station: '站点甲',
    section: '区间甲',
    activeDurationSeconds: 7.574,
    color: '#2f80ed',
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

    const roleRows = wrapper.findAll('.trackside-tooltip-entry__role')
    expect(roleRows.map((item) => item.text())).toEqual([
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
    expect(roleRows.every((item) => !item.text().includes('AP'))).toBe(true)
    expect(wrapper.text()).not.toMatch(/ACTIVE　AP-A|STANDBY　AP-B/)
    expect(wrapper.text()).not.toMatch(/Peer Radio MAC|Peer MAC|数据来源|dBm|series_id|run_id|link_id/i)
    expect(wrapper.classes()).toContain('is-right')
    expect(wrapper.attributes('style')).toContain('max-height: 640px')
  })

  it('renders every long-frame entry and emits a pin action without the old empty state', async () => {
    const longEntries = Array.from({ length: 13 }, (_, index): TracksideTooltipEntry => ({
      ...entries[index === 0 ? 1 : 0],
      seriesId: `series-${index}`,
      metaId: index,
      apName: `AP-${index}`,
      role: index === 0 ? 'ACTIVE' : 'STANDBY',
    }))
    const wrapper = mount(TracksideExternalTooltip, {
      props: {
        visible: true,
        timestamp: '2024-10-22 14:40:15.181',
        entries: longEntries,
        availableHeight: 676,
      },
    })

    expect(wrapper.findAll('.trackside-tooltip-entry')).toHaveLength(13)
    expect(wrapper.attributes('style')).toContain('max-height: 640px')
    expect(wrapper.text()).not.toContain('当前时刻无有效采样')
    await wrapper.get('.trackside-external-tooltip__pin').trigger('click')
    expect(wrapper.emitted('pin')).toHaveLength(1)
  })

  it('does not render a tooltip shell for empty entries', () => {
    const wrapper = mount(TracksideExternalTooltip, {
      props: { visible: true, entries: [] },
    })
    expect(wrapper.find('[data-trackside-external-tooltip]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('当前时刻无有效采样')
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
