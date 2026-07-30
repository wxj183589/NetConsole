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
import { t } from '../i18n/runtime'

const DESKTOP_SESSION_HEADER = 'X-NetConsole-Session'

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code = '', readonly details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export interface ApiErrorDetail {
  path: string
  code: string
  status: number
  requestId: string
  message: string
  originalMessage: string
}

export function apiErrorDetail(reason: unknown, fallbackPath = ''): ApiErrorDetail {
  if (reason instanceof ApiRequestError) {
    const path = String(reason.details.path || fallbackPath)
    const originalMessage = String(
      reason.details.original_message
      || reason.details.network_error
      || reason.details.response_error
      || reason.message,
    )
    return {
      path,
      code: reason.code || 'HTTP_ERROR',
      status: reason.status,
      requestId: String(reason.details.request_id || ''),
      message: reason.message,
      originalMessage,
    }
  }
  const message = reason instanceof Error ? reason.message : String(reason || '未知错误')
  return {
    path: fallbackPath,
    code: 'UNEXPECTED_ERROR',
    status: 0,
    requestId: '',
    message,
    originalMessage: message,
  }
}

async function readJsonResponse<T>(
  response: Response,
  path: string,
  errorCode: 'HTTP_ERROR' | 'INVALID_JSON_RESPONSE',
): Promise<T> {
  if (typeof response.text !== 'function') {
    try {
      return await response.json() as T
    } catch (cause) {
      throw new ApiRequestError(
        response.ok
          ? t('api.backend_incomplete', 'Backend 返回内容不完整，请重试。')
          : `${t('api.request_failed', '请求失败')} (${response.status})`,
        response.status,
        response.ok ? errorCode : 'HTTP_ERROR',
        {
          path,
          response_error: cause instanceof Error ? cause.message : String(cause),
        },
      )
    }
  }
  let text: string
  try {
    text = await response.text()
  } catch (cause) {
    console.error('API_RESPONSE_BODY_FAILED', {
      path,
      status: response.status,
      error: cause instanceof Error ? cause.message : String(cause),
    })
    throw new ApiRequestError(
      t('api.backend_body_interrupted', 'Backend 返回内容读取中断，请重试。'),
      response.status,
      'RESPONSE_BODY_FAILED',
      {
        path,
        original_message: cause instanceof Error ? cause.message : String(cause),
      },
    )
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiRequestError(
      response.ok
        ? t('api.backend_incomplete', 'Backend 返回内容不完整，请重试。')
        : `${t('api.request_failed', '请求失败')} (${response.status})`,
      response.status,
      errorCode,
      {
        path,
        original_message: response.ok
          ? 'Backend 返回内容不是有效 JSON'
          : `HTTP ${response.status} 响应不是有效 JSON`,
      },
    )
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const runtime = getRuntimeConfig()
  const formData = typeof FormData !== 'undefined' && options.body instanceof FormData
  if (!formData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (runtime.apiToken) headers.set(DESKTOP_SESSION_HEADER, runtime.apiToken)
  const url = resolveApiUrl(path)
  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
      credentials: options.credentials ?? (runtime.hostType === 'electron' ? 'include' : 'same-origin'),
    })
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') {
      const aborted = new ApiRequestError(
        t('api.request_cancelled', '请求已取消'),
        0,
        'REQUEST_ABORTED',
        { path },
      )
      aborted.name = 'AbortError'
      throw aborted
    }
    console.error('API_REQUEST_NETWORK_FAILED', {
      path,
      error: cause instanceof Error ? cause.message : String(cause),
    })
    const networkMessage = cause instanceof Error ? cause.message : String(cause)
    const code = /backend restart|process exited/i.test(networkMessage)
      ? 'BACKEND_RESTARTED'
      : /timeout|timed out/i.test(networkMessage)
      ? 'RAW_QUERY_TIMEOUT'
      : /connection reset|econnreset|socket hang up/i.test(networkMessage)
      ? 'CONNECTION_RESET'
      : 'BACKEND_CONNECTION_INTERRUPTED'
    throw new ApiRequestError(
      t('api.backend_connection_interrupted', 'Backend 连接中断，请重试。'),
      0,
      code,
      {
        path,
        network_error: networkMessage,
      },
    )
  }
  if (!response.ok) {
    let message = `${t('api.request_failed', '请求失败')} (${response.status})`
    let code = ''
    let details: Record<string, unknown> = {}
    try {
      const body = await readJsonResponse<{
        detail?: string | { code?: string; message?: string; details?: Record<string, unknown> }
        error?: { code?: string; message?: string; details?: Record<string, unknown> }
      }>(response, path, 'HTTP_ERROR')
      const detail = typeof body.detail === 'string' ? null : body.detail
      message = typeof body.detail === 'string' ? body.detail : detail?.message || body.error?.message || message
      code = detail?.code || body.error?.code || ''
      details = detail?.details || body.error?.details || {}
    } catch (reason) {
      if (reason instanceof ApiRequestError) {
        message = reason.message
        code = reason.code
        details = reason.details
      }
    }
    throw new ApiRequestError(message, response.status, code || 'HTTP_ERROR', {
      ...details,
      path: details.path || path,
      request_id: details.request_id || response.headers?.get?.('X-Request-ID') || '',
      original_message: details.original_message || message,
    })
  }
  return readJsonResponse<T>(response, path, 'INVALID_JSON_RESPONSE')
}

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/health')
}

export async function getWebBuildMeta(): Promise<WebBuildMeta> {
  const response = await fetch(resolveFrontendAssetUrl('/web-build-meta.json'), { cache: 'no-store' })
  if (!response.ok) throw new Error(`前端构建元数据不可用 (${response.status})`)
  return (await response.json()) as WebBuildMeta
}
