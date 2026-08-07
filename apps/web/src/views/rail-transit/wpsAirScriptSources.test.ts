import { describe, expect, it } from 'vitest'

import { wpsAirScriptSource, type WpsAirScriptKind } from './wpsAirScriptSources'
import type { WpsTracksideTargetCode } from '../../types/tracksideApBusiness'

const scripts: Array<{
  targetCode: WpsTracksideTargetCode
  kind: WpsAirScriptKind
  scriptVersion: string
  deploymentId: string
  documentId: string
  targetType: string
}> = [
  {
    targetCode: 'wps_standard_spreadsheet',
    kind: 'probe',
    scriptVersion: '2.1.0-standard',
    deploymentId: 'trackside-ap-standard-2.1.0',
    documentId: '549847228994',
    targetType: 'WPS_STANDARD_SPREADSHEET',
  },
  {
    targetCode: 'wps_standard_spreadsheet',
    kind: 'sync',
    scriptVersion: '2.1.0-standard',
    deploymentId: 'trackside-ap-standard-2.1.0',
    documentId: '549847228994',
    targetType: 'WPS_STANDARD_SPREADSHEET',
  },
  {
    targetCode: 'wps_smart_sheet',
    kind: 'probe',
    scriptVersion: '2.1.0-smart',
    deploymentId: 'trackside-ap-smart-2.1.0',
    documentId: 'cbRdGQdb10R9',
    targetType: 'WPS_SMART_SHEET',
  },
  {
    targetCode: 'wps_smart_sheet',
    kind: 'sync',
    scriptVersion: '2.1.0-smart',
    deploymentId: 'trackside-ap-smart-2.1.0',
    documentId: 'cbRdGQdb10R9',
    targetType: 'WPS_SMART_SHEET',
  },
]

describe('WPS AirScript deployment sources', () => {
  it.each(scripts)(
    'returns $targetCode $kind with an explicit top-level result',
    ({ targetCode, kind, scriptVersion, deploymentId, documentId, targetType }) => {
      const source = wpsAirScriptSource(targetCode, kind)

      expect(source.trimEnd()).toMatch(/return main\(\);$/)
      expect(source).not.toMatch(/^\s*main\(\);\s*$/m)
      expect(source).toContain(`const SCRIPT_VERSION = "${scriptVersion}";`)
      expect(source).toContain(`const DEPLOYMENT_ID = "${deploymentId}";`)
      expect(source).toContain(`const DOCUMENT_ID = "${documentId}";`)
      expect(source).toContain(`const TARGET_TYPE = "${targetType}";`)
      expect(source).toContain(`const TARGET_CODE = "${targetCode}";`)
    },
  )

  it.each(scripts.filter(({ kind }) => kind === 'probe'))(
    'keeps $targetCode connection probe read-only',
    ({ targetCode, kind }) => {
      const source = wpsAirScriptSource(targetCode, kind)

      expect(source).toContain('verification: "CONNECTION_PROBE_ONLY"')
      expect(source).not.toMatch(/\.Add\(|\.Insert\(|\.ClearContents\(|\.Value\s*=|CreateRecords|DeleteRecords|EnsureFields|DeleteWhere|AddRecords/)
      expect(source).not.toContain('sync_trackside_ap_business')
    },
  )
})
