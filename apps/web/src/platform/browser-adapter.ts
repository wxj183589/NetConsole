import type { PlatformAdapter } from './types'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

const DESKTOP_ONLY_MESSAGE = '当前能力仅在 NetConsole Electron Desktop 中可用'
const INVALID_FILE_NAME_RE = /[\u0000-\u001f<>:"/\\|?*]/
const QUERY_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/
const SENSITIVE_QUERY_KEY_RE = /(?:token|password|secret|authorization|community|passphrase)/i
const DEVELOPMENT_TOKEN_RE = /^[A-Za-z0-9_-]{32,256}$/
const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'

export function createBrowserAdapter(apiBaseUrl = '', developmentToken = ''): PlatformAdapter {
  const baseUrl = normalizeBaseUrl(apiBaseUrl)
  const apiToken = validateDevelopmentToken(developmentToken)
  if (apiToken) validateDevelopmentBaseUrl(baseUrl)
  return {
    hostType: 'browser',
    getAppInfo: async () => ({ version: '', platform: 'browser', isPackaged: false }),
    getBackendStatus: async () => ({ state: 'stopped' }),
    getRuntimeConfig: async () => {
      if (apiToken) await createDevelopmentSession(baseUrl, apiToken)
      return { apiBaseUrl: baseUrl, apiToken }
    },
    selectFile: async () => ({ cancelled: true, paths: [] }),
    selectDirectory: async () => ({ cancelled: true }),
    selectSettingsTool: async () => ({ cancelled: true }),
    selectSettingsDirectory: async () => ({ cancelled: true }),
    selectSettingsColor: async () => ({ cancelled: true }),
    executeSettingsAction: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    chooseSavePath: async () => ({ cancelled: true }),
    downloadBackendResource: async (value) => startBrowserDownload(value, baseUrl),
    openTaskWindow: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    openPath: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    showItemInFolder: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    openExternalUrl: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    onBackendStatusChanged: () => () => undefined,
    reportRendererReady: () => undefined,
  }
}

async function createDevelopmentSession(apiBaseUrl: string, apiToken: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/dev/session`, {
    method: 'POST',
    credentials: 'include',
    headers: { [DESKTOP_SESSION_HEADER]: apiToken },
  })
  if (!response.ok) throw new Error(`本机开发会话初始化失败 (${response.status})`)
}

function validateDevelopmentToken(value: string): string {
  const token = value.trim()
  if (!token) return ''
  if (!DEVELOPMENT_TOKEN_RE.test(token)) throw new Error('开发会话令牌格式无效')
  return token
}

function validateDevelopmentBaseUrl(value: string): void {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error('开发 API 必须使用 127.0.0.1 回环地址')
  }
  if (
    url.protocol !== 'http:'
    || url.hostname !== '127.0.0.1'
    || !url.port
    || url.username
    || url.password
    || url.pathname !== '/'
    || url.search
    || url.hash
  ) {
    throw new Error('开发 API 必须使用 127.0.0.1 回环地址')
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
