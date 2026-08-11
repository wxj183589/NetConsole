import standardProbe from '../../../../../tools/wps_airscript/trackside_ap_standard_spreadsheet_connection_probe.js?raw'
import standardSync from '../../../../../tools/wps_airscript/trackside_ap_standard_spreadsheet_sync.js?raw'

import type { WpsTracksideTarget, WpsTracksideTargetCode } from '../../types/tracksideApBusiness'
import { normalizeWpsUrlInput } from './wpsUrlInput'

export type WpsAirScriptKind = 'probe' | 'sync'

const sources: Record<WpsTracksideTargetCode, Record<WpsAirScriptKind, string>> = {
  wps_standard_spreadsheet: { probe: standardProbe, sync: standardSync },
}

const documentIdMarker = '__NETCONSOLE_DOCUMENT_ID__'

export function wpsAirScriptSource(
  target: Pick<WpsTracksideTarget, 'target_code' | 'document_open_url' | 'webhook_url' | 'expected_document_id'>,
  kind: WpsAirScriptKind,
): string {
  const document = normalizeWpsUrlInput(target.document_open_url, 'document')
  const webhook = normalizeWpsUrlInput(target.webhook_url, 'webhook')
  const documentId = webhook.webhookIdentity?.documentId || ''
  if (!document.url || !documentId || documentId !== target.expected_document_id) {
    throw new Error('请先填写有效的 WPS Webhook 地址，以确定当前文档 ID。')
  }
  const source = sources[target.target_code][kind]
  if (source.split(documentIdMarker).length !== 2) {
    throw new Error('WPS 脚本模板身份标记无效')
  }
  return source.replace(documentIdMarker, documentId)
}
