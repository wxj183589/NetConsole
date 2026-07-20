import { describe, expect, it } from 'vitest'

import { meshArtifactDownloadRequest } from '../../api/meshAnalysis'
import source from './MeshAnalysisView.vue?raw'

describe('Mesh analysis view', () => {
  it('shows persisted results and real import and report actions', () => {
    expect(source).toContain('Mesh 原始日志分析')
    expect(source).toContain('主 / 备链路')
    expect(source).toContain('主链路时间线')
    expect(source).toContain('切换事件')
    expect(source).toContain('RSSI')
    expect(source).toContain('TxBusy / RxBusy')
    expect(source).toContain('Rate（原始值）')
    expect(source).toContain('Retry / Error 增量')
    expect(source).toContain('切换前后 RSSI')
    expect(source).toContain('MeshRateChart')
    expect(source).toContain('MeshCounterDeltaChart')
    expect(source).toContain('MeshSwitchRssiChart')
    expect(source).not.toContain('MeshUnavailableChart')
    expect(source).not.toContain('fping / iPerf 对齐')
    expect(source).not.toContain('getMeshAlignment')
    expect(source).toContain('报告与来源')
    expect(source).toContain('<el-pagination')
    expect(source).not.toContain('peer_radio_mac')
    expect(source).not.toContain('归属来源')
    expect(source).toContain('importMeshAnalysis')
    expect(source).toContain('previewMeshBundle')
    expect(source).toContain('applyMeshBundleImport')
    expect(source).toContain('safe_name')
    expect(source).toContain('explicit_confirmation: true')
    expect(source).toContain('createMeshProfile')
    expect(source).toContain('exportMeshAnalysisReport')
    expect(source).toContain('recoverRailTransitTasks')
    expect(source).toContain('rebuildMeshAnalysis')
    expect(source).toContain('mesh_schema_rebuild')
    expect(source).toContain('Promise.allSettled')
    expect(source).toContain('旧版指标区域不可用')
    expect(source).toContain("openTaskWindow({ module: 'rail'")
    expect(source).not.toContain('cancelRailTransitTask')
    expect(source).toContain('生成分析报告')
    expect(source).toContain("router.push('/rail-transit/train-online')")
    expect(source).not.toContain("router.push('/ac-management/mesh-links')")
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
    expect(source).not.toMatch(/>s*删除s*</)
  })

  it('keeps raw tail collapsed behind an explicit action and stops polling on unmount', () => {
    expect(source).toContain('tail_available')
    expect(source).toContain('loadRawTail')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('clearTimeout')
    expect(source).toContain("document.visibilityState === 'visible'")
    expect(source).toContain('failureCount >= 3 ? 90_000 : 30_000')
    expect(source).not.toContain('setInterval')
    expect(source).not.toContain('absolute_path')
  })

  it('uses the unified platform download instead of navigating the renderer', () => {
    expect(source).toContain('meshArtifactDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain('meshArtifactDownloadUrl')
    expect(source).not.toContain(':href=')
    expect(meshArtifactDownloadRequest('会话/1', '报告/1', 'mesh.zip')).toEqual({
      apiPath: '/api/rail-transit/mesh-analysis/sessions/%E4%BC%9A%E8%AF%9D%2F1/artifacts/%E6%8A%A5%E5%91%8A%2F1/download',
      suggestedName: 'mesh.zip',
    })
  })

  it('uses typed shared tables with stable identities and scoped detail preferences', () => {
    expect(source).toContain("import NcDataTable from '../../components/table/NcDataTable.vue'")
    expect(source).toContain('NcTableColumn<MeshAnalysisSession>[]')
    expect(source).toContain('NcTableColumn<MeshLinkDetail>[]')
    expect(source).toContain('NcTableColumn<MeshAnomaly>[]')
    expect(source).not.toContain('<el-table')
    expect(source).not.toContain('<el-table-column')
    expect(source).toContain(':preference-scope="selected.session.session_id"')
    expect(source).toContain(':preference-scope="task.task_id"')
    expect(source).toContain("alignmentReason: 'long-text'")
    expect(source).toContain("alignmentReason: 'path'")

    const tableIds = [...source.matchAll(/table-id="([^"]+)"/g)].map((match) => match[1])
    expect(tableIds.length).toBeGreaterThanOrEqual(10)
    expect(new Set(tableIds).size).toBe(tableIds.length)
  })
})
