import { describe, expect, it } from 'vitest'

import source from './TrainCommunicationView.vue?raw'

describe('固定车载通信拓扑页面', () => {
  it('使用固定拓扑和正式在线列车诊断 API', () => {
    expect(source).toContain('FixedTrainTopology')
    expect(source).toContain('getTrainCommunicationTopology')
    expect(source).toContain('startTrainCommunicationCheck')
    expect(source).toContain('getTrainCommunicationCheck')
    expect(source).toContain('立即检测')
    expect(source).toContain('TC1 / TC2')
    expect(source).toContain('CarNetworkPointTableDialog')
    expect(source).toContain('检测点表未配置')
    expect(source).toContain('在线列车车内通信检测')
    expect(source).toContain('active_only: true')
    expect(source).toContain("topology.value?.point_table_status === 'configured'")
  })

  it('不嵌入综合无线指标或 Online MR 控制', () => {
    expect(source).toContain('Mesh-Link 和核心侧检测仅作为辅助接入证据')
    expect(source).not.toMatch(/OnlineMrLocalControl|OnlineMrAgentControlPanel|RSSI|fping|丢包|iPerf|光衰|轨旁 AP|NcDataTable|Agent/)
    expect(source).not.toMatch(/unknown|no_data/)
  })

  it('卸载时清理刷新和检测任务定时器', () => {
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain("clearTimer('refresh')")
    expect(source).toContain("clearTimer('check')")
  })
})
