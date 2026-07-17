export interface HealthResponse {
  status: string
  version: string
  build_id: string
}

export interface WebBuildMeta {
  app_version: string
  git_commit: string
  build_time: string
  navigation_schema_version: number
  build_id: string
}

import {
  getRuntimeConfig,
  resolveApiUrl,
  resolveFrontendAssetUrl,
} from '../platform/runtime'

const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const runtime = getRuntimeConfig()
  const formData = typeof FormData !== 'undefined' && options.body instanceof FormData
  if (!formData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (runtime.apiToken) headers.set(DESKTOP_SESSION_HEADER, runtime.apiToken)
  const response = await fetch(resolveApiUrl(path), {
    ...options,
    headers,
    credentials: options.credentials ?? (runtime.hostType === 'electron' ? 'include' : 'same-origin'),
  })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const body = (await response.json()) as {
        detail?: string | { message?: string }
        error?: { message?: string }
      }
      message = typeof body.detail === 'string' ? body.detail : body.detail?.message || body.error?.message || message
    } catch {
      // 保留稳定的 HTTP 状态错误。
    }
    throw new ApiRequestError(message, response.status)
  }
  return (await response.json()) as T
}

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/health')
}

export async function getWebBuildMeta(): Promise<WebBuildMeta> {
  const response = await fetch(resolveFrontendAssetUrl('/web-build-meta.json'), { cache: 'no-store' })
  if (!response.ok) throw new Error(`前端构建元数据不可用 (${response.status})`)
  return (await response.json()) as WebBuildMeta
}
