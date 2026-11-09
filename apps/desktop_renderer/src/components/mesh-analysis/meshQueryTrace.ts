export type MeshTraceStage = 'interaction' | 'cache' | 'http' | 'sql' | 'result' | 'error'

export interface MeshQueryTraceEvent {
  operation_id: string
  query_kind: string
  stage: MeshTraceStage
  cache_status?: 'hit' | 'miss' | 'gap' | 'bypass'
  http_requests?: number
  sql_queries?: number
  detail?: string
  at: number
}

type TraceResult = { sql_query_count?: number; query_id?: string | null; query_kind?: string | null }

const TRACE_GLOBAL = '__NETCONSOLE_MESH_TRACE__'
export const MESH_TRACE_ENABLED = import.meta.env.DEV || import.meta.env.MODE === 'test'

function publish(events: MeshQueryTraceEvent[]): void {
  if (typeof globalThis === 'undefined') return
  const target = globalThis as typeof globalThis & { [TRACE_GLOBAL]?: MeshQueryTraceEvent[] }
  target[TRACE_GLOBAL] = events
}

/** Bounded workbench-only ledger for Interaction -> Cache -> HTTP -> SQL evidence. */
export class MeshQueryTrace {
  private readonly events: MeshQueryTraceEvent[] = []
  private readonly maxEvents: number
  private sequence = 0

  constructor(maxEvents = 2048) {
    this.maxEvents = Math.max(32, maxEvents)
  }

  begin(queryKind: string, detail = ''): string {
    if (!MESH_TRACE_ENABLED) return ''
    const operationId = `mesh-op-${Date.now().toString(36)}-${(++this.sequence).toString(36)}`
    this.add({ operation_id: operationId, query_kind: queryKind, stage: 'interaction', detail })
    return operationId
  }

  cache(operationId: string, queryKind: string, status: 'hit' | 'miss' | 'gap' | 'bypass', detail = ''): void {
    this.add({ operation_id: operationId, query_kind: queryKind, stage: 'cache', cache_status: status, detail })
  }

  http(operationId: string, queryKind: string, result?: unknown): void {
    const metadata = result && typeof result === 'object' ? result as TraceResult : undefined
    this.add({ operation_id: operationId, query_kind: queryKind, stage: 'http', http_requests: 1, detail: metadata?.query_id ? `query_id=${metadata.query_id}` : '' })
    this.add({ operation_id: operationId, query_kind: queryKind, stage: 'sql', sql_queries: metadata?.sql_query_count || 0 })
  }

  error(operationId: string, queryKind: string, error: unknown): void {
    this.add({ operation_id: operationId, query_kind: queryKind, stage: 'error', detail: error instanceof Error ? error.message : String(error) })
  }

  snapshot(): MeshQueryTraceEvent[] {
    return this.events.slice()
  }

  clear(): void {
    this.events.length = 0
    publish(this.events)
  }

  private add(event: Omit<MeshQueryTraceEvent, 'at'>): void {
    if (!MESH_TRACE_ENABLED) return
    this.events.push({ ...event, at: Date.now() })
    while (this.events.length > this.maxEvents) this.events.shift()
    publish(this.events)
  }
}

export const meshQueryTrace = new MeshQueryTrace()

export function tracedMeshValues<T extends Record<string, unknown>>(values: T, operationId: string): T & { mesh_trace: true; mesh_operation_id: string } {
  if (!MESH_TRACE_ENABLED || !operationId) return values as T & { mesh_trace: true; mesh_operation_id: string }
  return { ...values, mesh_trace: true, mesh_operation_id: operationId }
}
