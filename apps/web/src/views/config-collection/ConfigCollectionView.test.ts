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

  it('keeps collection read-only and exposes controlled artifact download', () => {
    expect(source).toContain('采集 running / saved')
    expect(source).toContain('configArtifactUrl(row.artifact_id)')
    expect(source).toContain('保存配置')
    expect(source).not.toContain('save force')
    expect(source).not.toContain('删除快照')
    expect(source).not.toContain('任意路径')
  })
})
