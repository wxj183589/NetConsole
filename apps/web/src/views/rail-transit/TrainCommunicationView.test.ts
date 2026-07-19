import { describe, expect, it } from 'vitest'

import source from './TrainCommunicationView.vue?raw'

describe('固定车载通信拓扑页面', () => {
  it('使用固定拓扑和现有车内通信任务 API', () => {
    expect(source).toContain('FixedTrainTopology')
    expect(source).toContain('getTrainCommunicationTopology')
    expect(source).toContain('startTrainCommunicationCheck')
    expect(source).toContain('getTrainCommunicationCheck')
    expect(source).toContain('立即检测')
    expect(source).toContain('TC1 / TC2')
    expect(source).toContain('CarNetworkPointTableDialog')
    expect(source).toContain('检测点表未配置')
    expect(source).toContain("topology.value?.point_table_status === 'configured'")
  })

  it('不嵌入综合无线指标或 Online MR 控制', () => {
    expect(source).not.toMatch(/OnlineMrLocalControl|OnlineMrAgentControlPanel|RSSI|fping|丢包|iPerf|光衰|轨旁 AP|NcDataTable|Mesh-Link|Agent/)
    expect(source).not.toMatch(/unknown|no_data/)
  })

  it('卸载时清理刷新和检测任务定时器', () => {
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain("clearTimer('refresh')")
    expect(source).toContain("clearTimer('check')")
  })
})
