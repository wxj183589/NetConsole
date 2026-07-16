import { describe, expect, it } from 'vitest'

import source from './ConfigCollectionView.vue?raw'

describe('Configuration Collection Center view', () => {
  it('restores devices and snapshots while delegating task management to the shared window', () => {
    expect(source).toContain('listConfigDevices')
    expect(source).toContain('listConfigSnapshots')
    expect(source).toContain('listConfigTasks')
    expect(source).toContain('打开任务窗口')
    expect(source).toContain("openTaskWindow({ module: 'config' })")
    expect(source).toContain("router.push({ name: 'tasks', query: { module: 'config' } })")
    expect(source).not.toContain(':data="visibleTasks"')
    expect(source).not.toContain('<h2>配置任务</h2>')
    expect(source).toContain('document.hidden')
    expect(source).toContain('onBeforeUnmount')
  })

  it('gates each destructive, save, export and desktop action independently', () => {
    expect(source).toContain("isFeatureEnabled('web.config_collection_fetch')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_diff')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_download')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_delete')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_save_force')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_export')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_open_directory')")
    expect(source).toContain("isFeatureEnabled('web.job_center')")
  })

  it('uses server confirmation tokens, fixed save plan and controlled artifacts', () => {
    expect(source).toContain('采集 running / saved')
    expect(source).toContain('configArtifactDownloadRequest(snapshot.artifact_id, snapshot.filename)')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain('tag="a"')
    expect(source).toContain('保存配置')
    expect(source).toContain('issueSnapshotDelete')
    expect(source).toContain('confirmSnapshotDelete')
    expect(source).toContain('previewSaveForce')
    expect(source).toContain('confirmSaveForce')
    expect(source).toContain('submitConfigDiffExport')
    expect(source).toContain('submitConfigSnapshotsExport')
    expect(source).not.toContain('任意路径')
  })

  it('renders Qt-equivalent side-by-side rows with all change filters and navigation', () => {
    expect(source).toContain('resultDiffRows')
    expect(source).toContain('resultDiffSummary')
    expect(source).toContain('配置差异双栏视图')
    expect(source).toContain('仅新增')
    expect(source).toContain('仅删除')
    expect(source).toContain('仅修改')
    expect(source).toContain('上一处差异')
    expect(source).toContain('下一处差异')
    expect(source).toContain("row.status === '~'")
  })

  it('distinguishes partial and total deletion failures from success', () => {
    expect(source).toContain('failed_items')
    expect(source).toContain('任务部分完成')
    expect(source).toContain('部分完成')
    expect(source).toContain("Number(result.failed) === Number(result.total) ? '任务失败'")
    expect(source).toContain('unknown_items')
    expect(source).toContain('not_started_items')
    expect(source).toContain('任务中断，执行记录已保留')
  })
})
