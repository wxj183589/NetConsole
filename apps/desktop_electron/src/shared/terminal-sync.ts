import type { TerminalSyncRequest } from './bridge'

export function validateTerminalSyncRequest(value: unknown): TerminalSyncRequest {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('终端同步请求无效')
  const request = value as Record<string, unknown>
  const count = Object.keys(request).length
  if (request.action === 'list' && count === 1) return { action: 'list' }
  if (request.action === 'ready' && count === 2 && typeof request.ready === 'boolean') return { action: 'ready', ready: request.ready }
  if (request.action === 'select' && count === 2 && Array.isArray(request.ids) && request.ids.length <= 32
    && request.ids.every(id => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id))) {
    return { action: 'select', ids: [...new Set(request.ids as string[])] }
  }
  if (request.action === 'input' && count === 3 && (request.kind === 'keys' || request.kind === 'paste')
    && typeof request.data === 'string' && request.data.length > 0 && request.data.length <= 1_048_576) {
    return { action: 'input', kind: request.kind, data: request.data }
  }
  throw new Error('终端同步请求无效')
}
