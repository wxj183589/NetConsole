export type WpsUrlKind = 'document' | 'webhook'

export class WpsUrlInputError extends Error {
  constructor(
    readonly code: 'WPS_DOCUMENT_URL_INVALID' | 'WPS_WEBHOOK_INVALID' | 'WPS_DOCUMENT_URL_AMBIGUOUS',
    message: string,
  ) {
    super(message)
    this.name = 'WpsUrlInputError'
  }
}

export interface WpsWebhookIdentity {
  documentId: string
  scriptId: string
}

export interface NormalizedWpsUrl {
  url: string
  extracted: boolean
  webhookIdentity?: WpsWebhookIdentity
}

const webhookPath = /^\/api\/v3\/ide\/file\/([A-Za-z0-9_-]{3,160})\/script\/([A-Za-z0-9_-]{3,160})\/sync_task$/
const httpsUrl = /https:\/\/[^\s<>'"\[\]()]+/gi

export function normalizeWpsUrlInput(raw: string, kind: WpsUrlKind): NormalizedWpsUrl {
  const value = raw.trim()
  const candidates = [...new Set((value.match(httpsUrl) || []).map((item) => item.replace(/[.,;:]+$/, '')))]
  const trusted = candidates.map((item) => parseTrustedWpsUrl(item, kind))

  if (trusted.length !== 1) {
    if (trusted.length > 1) {
      throw new WpsUrlInputError(
        'WPS_DOCUMENT_URL_AMBIGUOUS',
        '检测到多个 WPS 链接，请只保留当前文档的一个链接',
      )
    }
    throw invalidUrl(kind)
  }
  const parsed = trusted[0]
  return {
    url: parsed.url,
    extracted: value !== parsed.url,
    ...(parsed.webhookIdentity ? { webhookIdentity: parsed.webhookIdentity } : {}),
  }
}

export function tryParseWpsWebhookIdentity(value: string): WpsWebhookIdentity | undefined {
  try {
    return normalizeWpsUrlInput(value, 'webhook').webhookIdentity
  } catch {
    return undefined
  }
}

function parseTrustedWpsUrl(value: string, kind: WpsUrlKind): NormalizedWpsUrl {
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw invalidUrl(kind)
  }
  const hostname = parsed.hostname.toLowerCase()
  if (parsed.protocol !== 'https:' || !(hostname === 'kdocs.cn' || hostname.endsWith('.kdocs.cn'))) {
    throw invalidUrl(kind)
  }
  if (kind === 'document') {
    if (!parsed.pathname.startsWith('/l/')) throw invalidUrl(kind)
    return { url: parsed.toString(), extracted: false }
  }
  const matched = webhookPath.exec(parsed.pathname)
  if (!matched) throw invalidUrl(kind)
  return {
    url: parsed.toString(),
    extracted: false,
    webhookIdentity: { documentId: matched[1], scriptId: matched[2] },
  }
}

function invalidUrl(kind: WpsUrlKind): WpsUrlInputError {
  return new WpsUrlInputError(
    kind === 'document' ? 'WPS_DOCUMENT_URL_INVALID' : 'WPS_WEBHOOK_INVALID',
    kind === 'document'
      ? '请填写有效的 WPS 在线文档链接'
      : '请先填写有效的 WPS Webhook 地址，以确定当前文档 ID。',
  )
}
