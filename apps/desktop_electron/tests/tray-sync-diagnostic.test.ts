import { describe, expect, it } from 'vitest'

import { formatTraySyncDiagnostic } from '../src/main/tray-sync-diagnostic'

describe('TraySync startup diagnostic', () => {
  it('prints the three site IDs in a searchable, read-only line', () => {
    expect(formatTraySyncDiagnostic({
      backendSiteId: 'hz10',
      rendererSiteId: 'hz10',
      traySiteId: 'hz10',
    })).toBe('[TraySync] backend_site_id=hz10 renderer_site_id=hz10 tray_site_id=hz10')
  })

  it('does not allow names or log-control characters into diagnostic IDs', () => {
    expect(formatTraySyncDiagnostic({
      backendSiteId: '杭州地铁10号线',
      rendererSiteId: 'hz10\nsecret',
      traySiteId: undefined,
    })).toBe('[TraySync] backend_site_id=10 renderer_site_id=hz10secret tray_site_id=')
  })
})
