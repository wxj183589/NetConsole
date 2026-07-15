import { describe, expect, it } from 'vitest'

import source from './ConfigCollectionView.vue?raw'

describe('Configuration Collection Center view', () => {
  it('restores devices, snapshots and Task Center state after refresh', () => {
    expect(source).toContain('listConfigDevices')
    expect(source).toContain('listConfigSnapshots')
    expect(source).toContain('listConfigTasks')
    expect(source).toContain('刷新页面后可恢复')
    expect(source).toContain('document.hidden')
    expect(source).toContain('onBeforeUnmount')
  })

  it('gates fetch, diff and artifact download actions independently', () => {
    expect(source).toContain("isFeatureEnabled('web.config_collection_fetch')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_diff')")
    expect(source).toContain("isFeatureEnabled('web.config_collection_download')")
  })

  it('exposes controlled artifact download and formal snapshot deletion', () => {
    expect(source).toContain('采集 running / saved')
    expect(source).toContain('configArtifactUrl(row.artifact_id)')
    expect(source).toContain('保存配置')
    expect(source).toContain('submitSnapshotDelete')
    expect(source).toContain('cancelConfigTask')
    expect(source).not.toContain('save force')
    expect(source).not.toContain('任意路径')
  })
})
