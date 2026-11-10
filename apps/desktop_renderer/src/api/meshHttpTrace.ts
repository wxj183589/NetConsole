export interface MeshHttpTraceEvent {
  id: string
  operation_id: string
  method: string
  path: string
  query_params: Record<string, string | string[]>
  attempt: number
  started_at: number
  completed_at?: number
  duration_ms?: number
  status: number | null
  request_id: string
  query_id?: string | null
  query_kind?: string | null
  sql_query_count: number
  sql_query_ranges?: unknown[]
  raw_sample_complete?: boolean
  raw_sample_version?: string | null
  raw_context_count?: number
  coverage_time_from?: string | null
  coverage_time_to?: string | null
  total?: number
  item_count?: number
  cache_status?: string | null
  cancelled: boolean
  failure?: string
}

export interface MeshHttpTraceSnapshot {
  events: MeshHttpTraceEvent[]
  active_count: number
}

const TRACE_GLOBAL = '__NETCONSOLE_MESH_HTTP_TRACE__'
export const MESH_HTTP_TRACE_ENABLED = import.meta.env.DEV || import.meta.env.MODE === 'test'

type TraceHandle = { event: MeshHttpTraceEvent } | null
type TraceGlobal = MeshHttpTraceSnapshot & { snapshot: () => MeshHttpTraceSnapshot }

const events: MeshHttpTraceEvent[] = []
const MAX_EVENTS = 2_048
let activeCount = 0
let sequence = 0

function publish(): void {
  if (!MESH_HTTP_TRACE_ENABLED || typeof globalThis === 'undefined') return
  const target = globalThis as typeof globalThis & { [TRACE_GLOBAL]?: TraceGlobal }
  target[TRACE_GLOBAL] = { ...snapshot(), snapshot }
}

function snapshot(): MeshHttpTraceSnapshot {
  return { events: events.map(event => ({ ...event, query_params: { ...event.query_params } })), active_count: activeCount }
}

function queryParams(path: string): Record<string, string | string[]> {
  const result: Record<string, string | string[]> = {}
  const query = new URL(path, 'http://netconsole.local').searchParams
  for (const key of new Set([...query.keys()])) {
    const values = query.getAll(key)
    result[key] = values.length > 1 ? values : values[0] || ''
  }
  return result
}

function isMeshPath(path: string): boolean {
  return path.startsWith('/api/rail-transit/mesh-analysis')
}

function payloadMetadata(event: MeshHttpTraceEvent, payload: unknown): void {
  if (!payload || typeof payload !== 'object') return
  const value = payload as Record<string, unknown>
  for (const key of [
    'query_id', 'query_kind', 'sql_query_count', 'sql_query_ranges', 'raw_sample_complete',
    'raw_sample_version', 'raw_context_count', 'coverage_time_from', 'coverage_time_to',
    'cache_status', 'total',
  ]) {
    if (key in value) (event as unknown as Record<string, unknown>)[key] = value[key]
  }
  if (Array.isArray(value.items)) event.item_count = value.items.length
  const trace = value._query_trace
  if (trace && typeof trace === 'object') payloadMetadata(event, trace)
}

export function beginMeshHttpTrace(path: string, method: string, attempt: number): TraceHandle {
  if (!MESH_HTTP_TRACE_ENABLED || !isMeshPath(path)) return null
  const params = queryParams(path)
  const event: MeshHttpTraceEvent = {
    id: `mesh-http-${Date.now().toString(36)}-${(++sequence).toString(36)}`,
    operation_id: typeof params.mesh_operation_id === 'string' ? params.mesh_operation_id : '',
    method,
    path: new URL(path, 'http://netconsole.local').pathname,
    query_params: params,
    attempt,
    started_at: Date.now(),
    status: null,
    request_id: '',
    sql_query_count: 0,
    cancelled: false,
  }
  events.push(event)
  while (events.length > MAX_EVENTS) events.shift()
  activeCount += 1
  publish()
  return { event }
}

export function completeMeshHttpTrace(handle: TraceHandle, response: Response): void {
  if (!handle) return
  const event = handle.event
  if (event.completed_at !== undefined) return
  event.completed_at = Date.now()
  event.duration_ms = event.completed_at - event.started_at
  event.status = response.status
  event.request_id = response.headers?.get?.('X-Request-ID') || ''
  activeCount = Math.max(0, activeCount - 1)
  publish()
}

export function recordMeshHttpPayload(handle: TraceHandle, payload: unknown): void {
  if (!handle) return
  payloadMetadata(handle.event, payload)
  publish()
}

export function failMeshHttpTrace(handle: TraceHandle, error: unknown): void {
  if (!handle) return
  const event = handle.event
  if (event.completed_at === undefined) {
    event.completed_at = Date.now()
    event.duration_ms = event.completed_at - event.started_at
    activeCount = Math.max(0, activeCount - 1)
  }
  event.status = event.status ?? 0
  event.cancelled = error instanceof Error && error.name === 'AbortError'
  event.failure = error instanceof Error ? error.message : String(error)
  publish()
}

export function clearMeshHttpTrace(): void {
  events.length = 0
  activeCount = 0
  if (MESH_HTTP_TRACE_ENABLED) publish()
}

export function getMeshHttpTraceSnapshot(): MeshHttpTraceSnapshot {
  return snapshot()
}
