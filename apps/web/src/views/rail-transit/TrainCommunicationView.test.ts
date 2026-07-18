import { describe, expect, it } from 'vitest'

import source from './TrainCommunicationView.vue?raw'

describe('train communication Online MR control integration', () => {
  it('keeps control in selected formal MR and separates LOCAL from AGENT', () => {
    expect(source).toContain("import OnlineMrLocalControl")
    expect(source).toContain("import OnlineMrAgentControlPanel")
    expect(source).toContain('<OnlineMrLocalControl')
    expect(source).toContain('<OnlineMrAgentControlPanel')
    expect(source).toContain('LOCAL 本地执行')
    expect(source).toContain('AGENT 远程执行')
    expect(source).toContain('store.selectedMr')
    expect(source).toContain(':site-id="store.summary?.site_id')
    expect(source).toContain(':mr="store.selectedMr.mr"')
  })

  it('keeps LOCAL and AGENT execution in explicit tabs', () => {
    expect(source).toContain('LOCAL 本地执行')
    expect(source).toContain('AGENT 远程执行')
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
  })

  it('keeps the Qt communication indicators visible without migration copy', () => {
    expect(source).toContain('MR-CT')
    expect(source).toContain('MR-TC')
    expect(source).toContain('RSSI')
    expect(source).toContain('fping')
    expect(source).toContain('丢包')
    expect(source).toContain('iPerf')
    expect(source).toContain('仅光衰异常')
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
  })

  it('uses typed shared data tables for the train and MR detail tables', () => {
    expect(source).toContain("import NcDataTable")
    expect(source).toContain('NcTableColumn<TrainCommunicationRow>')
    expect(source.match(/<NcDataTable\b/g)).toHaveLength(4)
    expect(source).toContain('table-id="rail-train-communication-trains"')
    expect(source).toContain('table-id="rail-train-communication-collectors"')
    expect(source).toContain('table-id="rail-train-communication-tasks"')
    expect(source).toContain('table-id="rail-train-communication-packages"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).not.toContain('<el-table')
  })
})
