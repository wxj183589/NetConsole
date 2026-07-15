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
    expect(source).not.toContain('site_id')
    expect(source).not.toContain('artifact_path')
  })
})
