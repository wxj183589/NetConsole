import type { PlatformAdapter } from './types'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

const DESKTOP_ONLY_MESSAGE = '当前能力仅在 NetConsole Electron Desktop 中可用'
const INVALID_FILE_NAME_RE = /[\u0000-\u001f<>:"/\\|?*]/
const QUERY_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/
const SENSITIVE_QUERY_KEY_RE = /(?:token|password|secret|authorization|community|passphrase)/i

export function createBrowserAdapter(apiBaseUrl = ''): PlatformAdapter {
  const baseUrl = normalizeBaseUrl(apiBaseUrl)
  return {
    hostType: 'browser',
    getAppInfo: async () => ({ version: '', platform: 'browser', isPackaged: false }),
    getBackendStatus: async () => ({ state: 'stopped' }),
    getRuntimeConfig: async () => ({ apiBaseUrl: baseUrl, apiToken: '' }),
    selectFile: async () => ({ cancelled: true, paths: [] }),
    selectDirectory: async () => ({ cancelled: true }),
    chooseSavePath: async () => ({ cancelled: true }),
    downloadBackendResource: async (value) => startBrowserDownload(value, baseUrl),
    openPath: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    showItemInFolder: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    openExternalUrl: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    onBackendStatusChanged: () => () => undefined,
    reportRendererReady: () => undefined,
  }
}

function startBrowserDownload(
  value: BackendDownloadRequest,
  apiBaseUrl: string,
): { status: 'started' | 'failed'; error?: string } {
  const path = buildBrowserRequestPath(value)
  if (typeof document === 'undefined' || !document.body) {
    return { status: 'failed', error: '浏览器下载环境不可用' }
  }
  const href = apiBaseUrl ? `${apiBaseUrl}${path}` : path
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = value.suggestedName.trim()
  anchor.hidden = true
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  return { status: 'started' }
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

function buildBrowserRequestPath(request: BackendDownloadRequest): string {
  const apiPath = request.apiPath.trim()
  let decodedPath = ''
  try {
    decodedPath = decodeURIComponent(apiPath)
  } catch {
    throw new TypeError('apiPath contains invalid escaping')
  }
  if (
    !apiPath.startsWith('/api/')
    || apiPath.length > 4_096
    || /[\\?#\u0000-\u001f]/.test(apiPath)
    || apiPath.includes('//')
    || decodedPath.split('/').some((part) => part === '.' || part === '..')
  ) {
    throw new TypeError('apiPath must be a safe relative /api path')
  }
  const suggestedName = request.suggestedName.trim()
  if (
    !suggestedName
    || suggestedName.length > 180
    || suggestedName === '.'
    || suggestedName === '..'
    || INVALID_FILE_NAME_RE.test(suggestedName)
  ) {
    throw new TypeError('suggestedName must be a safe file name')
  }
  const entries = Object.entries(request.query ?? {})
  if (entries.length > 32) throw new TypeError('download query has too many fields')
  for (const [key, item] of entries) {
    if (
      !QUERY_KEY_RE.test(key)
      || SENSITIVE_QUERY_KEY_RE.test(key)
      || typeof item !== 'string'
      || item.length > 2_000
      || /[\u0000-\u001f]/.test(item)
    ) {
      throw new TypeError('download query is invalid')
    }
  }
  const query = new URLSearchParams(request.query)
  return `${apiPath}${query.size ? `?${query.toString()}` : ''}`
}
