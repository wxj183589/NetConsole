import { describe, expect, it } from 'vitest'

import source from './AcWebParityView.vue?raw'

describe('AC Web parity controlled view', () => {
  it('uses the durable import, guarded export and fixed action APIs', () => {
    expect(source).toContain('previewAcExtension')
    expect(source).toContain('applyAcExtension')
    expect(source).toContain('rollbackAcExtension')
    expect(source).toContain('exportAcExtensions')
    expect(source).toContain('confirmAcActionPlan')
    expect(source).toContain('executeAcActionPlan')
    expect(source).toContain('recoverAcWebTasks')
    expect(source).toContain('getAcWebTask')
    expect(source).toContain('cancelAcWebTask')
    expect(source).toContain('downloadAcExtensionArtifact')
    expect(source).toContain('localStorage')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('listAcTracksidePlan')
    expect(source).toContain('本地重算只读取当前数据库与缓存，不连接真实 AC')
    expect(source).not.toContain('site_id')
    expect(source).not.toContain('artifact_path')
    expect(source).not.toContain('source:')
    expect(source).not.toContain('refresh_scope')
  })
})
