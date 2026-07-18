import { describe, expect, it } from 'vitest'

import source from './RailTransitBaseDataView.vue?raw'

describe('Rail Transit base data controlled view', () => {
  it('shows all domains, server pagination and guarded import workflow', () => {
    expect(source).toContain('基础资料总览')
    expect(source).toContain('站点与区间')
    expect(source).toContain('轨旁 AP')
    expect(source).toContain('列车与车载 MR')
    expect(source).toContain('数据质量问题')
    expect(source).toContain('关联运行状态')
    expect(source).toContain('基础资料写入默认关闭')
    expect(source).toContain('只看阻断问题')
    expect(source).toContain('待人工确认')
    expect(source).toContain('CREATE')
    expect(source).toContain('CONFLICT')
    expect(source).toContain('字段差异')
    expect(source).toContain('写入未授权，仅可预览')
    expect(source).toContain('store.canApplyImport()')
    expect(source).toContain('我已核对差异、冲突和目标局点')
    expect(source).toContain('应用导入')
    expect(source).toContain('!applyConfirmed || previewBlocked')
    expect(source).toContain('导入审计')
    expect(source).toContain('回滚')
    expect(source).toContain('<el-pagination')
    expect(source).toContain('handleVisibility')
    expect(source).toContain('store.stopPolling()')
  })

  it('does not expose generic deletion, credentials or unguarded persistence', () => {
    expect(source).not.toMatch(/>\s*(覆盖数据库|删除)\s*<\/el-button>/)
    expect(source).toMatch(/v-if="store\.canApplyImport\(\)"/)
    expect(source).toMatch(/v-if="store\.importPolicies\?\.rollback_enabled/)
    expect(source).not.toContain('密码')
    expect(source).not.toContain('username')
    expect(source).not.toContain('client_count')
  })

  it('uses the shared typed data table contract for every base-data table', () => {
    expect(source).toContain("import NcDataTable from '../../components/table/NcDataTable.vue'")
    expect(source).toContain('NcTableColumn<Station>[]')
    expect(source).toContain('NcTableColumn<DataQualityIssue>[]')
    expect(source).toContain('NcTableColumn<MergeFieldDiff>[]')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
    expect(source).toContain('#cell-expand')
    expect(source).toContain(':preference-scope="row.entity_id"')
    expect(source).toContain(':preference-scope="String(row.row_number)"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).toContain("alignmentReason: 'path'")

    const tableIds = [...source.matchAll(/table-id="([^"]+)"/g)].map((match) => match[1])
    expect(tableIds.length).toBeGreaterThanOrEqual(12)
    expect(new Set(tableIds).size).toBe(tableIds.length)
  })
})
