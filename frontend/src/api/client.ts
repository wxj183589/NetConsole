export interface HealthResponse {
  status: string
  version: string
}

const apiBase = import.meta.env.VITE_API_BASE || ''

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const body = (await response.json()) as { detail?: string; error?: { message?: string } }
      message = body.detail || body.error?.message || message
    } catch {
      // 保留稳定的 HTTP 状态错误。
    }
    throw new Error(message)
  }
  return (await response.json()) as T
}

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/health')
}
