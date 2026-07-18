import { describe, expect, it } from 'vitest'

import source from './TracksideApBusinessView.vue?raw'

describe('trackside AP business view', () => {
  it('exposes the Qt query, scoped update, recovery and unified task-window boundaries', () => {
    for (const contract of [
      'listTracksideApBusiness', 'startTracksideApUpdate', 'recoverTracksideApTasks',
      'startTracksideApBusinessExport', 'tracksideApBusinessDownloadRequest', 'downloadBackendResource',
      "new Set(['trackside_ap_optical_update', 'trackside_ap_business_export'])",
      "openTaskWindow({ module: 'rail'",
      '更新全部光衰', '更新站点', '更新 AP', '导出表格', '保存导出表格', '仅光衰异常', '当前轨旁 AP',
      "isFeatureEnabled('web.rail_trackside_ap_business_update')",
      "isFeatureEnabled('web.rail_trackside_ap_business_export')",
    ]) expect(source).toContain(contract)
    expect(source).not.toContain('cancelTracksideApTask')
    expect(source).not.toContain('READ ONLY')
    expect(source).not.toContain('只读')
    expect(source).toContain('displayInterfaceName(row.interface_name)')
  })

  it('keeps the last successful page visible while a later refresh is running or fails', () => {
    expect(source).toContain('const initialLoading = ref(false)')
    expect(source).toContain('const refreshing = ref(false)')
    expect(source).toContain('const firstLoad = page.value === null')
    expect(source).toContain('page.value = nextPage')
    expect(source).not.toContain('page.value = null')
    expect(source).toContain(':current-page="page?.page || filters.page"')
    expect(source).toContain('v-loading="initialLoading"')
    expect(source).not.toContain('v-loading="refreshing"')
    expect(source).toContain('正在刷新，当前数据保持显示')
  })

  it('uses the standard data table and the strict optical presentation map', () => {
    expect(source).toContain("import NcDataTable from '../../components/table/NcDataTable.vue'")
    expect(source).toContain('const businessColumns: NcTableColumn<TracksideApBusinessRow>[]')
    expect(source).toContain('table-id="trackside-ap-business"')
    expect(source).toContain('table-id="trackside-ap-business-task-result"')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
    expect(source).toContain('tracksideOpticalPresentation(row.switch_optical_status)')
    expect(source).toContain('tracksideOpticalPresentation(row.ap_optical_status)')
    expect(source).toContain('tracksideOpticalPresentation(row.optical_severity)')
  })
})
