import smartProbe from '../../../../../tools/wps_airscript/trackside_ap_smart_sheet_connection_probe.js?raw'
import smartSync from '../../../../../tools/wps_airscript/trackside_ap_smart_sheet_sync.js?raw'
import standardProbe from '../../../../../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js?raw'
import standardSync from '../../../../../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js?raw'

import type { WpsTracksideTargetCode } from '../../types/tracksideApBusiness'

export type WpsAirScriptKind = 'probe' | 'sync'

const sources: Record<WpsTracksideTargetCode, Record<WpsAirScriptKind, string>> = {
  wps_standard_spreadsheet: { probe: standardProbe, sync: standardSync },
  wps_smart_sheet: { probe: smartProbe, sync: smartSync },
}

export function wpsAirScriptSource(
  targetCode: WpsTracksideTargetCode,
  kind: WpsAirScriptKind,
): string {
  return sources[targetCode][kind]
}
