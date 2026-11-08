export type MeshChartKind = 'rssi' | 'trackside' | 'busy'

export type MeshLoadingPhase =
  | 'IDLE'
  | 'PREPARING'
  | 'QUERYING'
  | 'PROCESSING'
  | 'RENDERING'
  | 'COMPLETED'
  | 'ERROR'
  | 'CANCELLED'

export interface MeshLoadingState {
  chart: MeshChartKind
  phase: MeshLoadingPhase
  message: string
  error?: string
  updated_at: string
}

export interface MeshChartRenderCompletePayload {
  chart: MeshChartKind
  phase: 'COMPLETED'
  point_count: number
  rendered_at: string
}

export interface MeshChartRenderErrorPayload {
  chart: MeshChartKind
  phase: 'ERROR'
  error: string
  failed_at: string
}

export const MESH_LOADING_PHASE_LABELS: Readonly<Record<MeshLoadingPhase, string>> = {
  IDLE: '未开始',
  PREPARING: '正在准备分析数据',
  QUERYING: '正在查询数据库',
  PROCESSING: '正在处理和计算数据',
  RENDERING: '正在绘制图表',
  COMPLETED: '加载完成',
  ERROR: '数据加载失败',
  CANCELLED: '已取消加载',
}

export const MESH_LOADING_PHASE_TEXT = MESH_LOADING_PHASE_LABELS

export const MESH_CHART_LABELS: Readonly<Record<MeshChartKind, string>> = {
  rssi: '主链 RSSI',
  trackside: '轨旁 AP 信号',
  busy: '空口负载',
}

export function meshLoadingPhaseLabel(phase: MeshLoadingPhase): string {
  return MESH_LOADING_PHASE_LABELS[phase]
}

export function isMeshLoadingActivePhase(phase: MeshLoadingPhase): boolean {
  return phase === 'PREPARING'
    || phase === 'QUERYING'
    || phase === 'PROCESSING'
    || phase === 'RENDERING'
}

export const meshLoadingPhaseText = meshLoadingPhaseLabel
export const meshLoadingPhaseMessage = meshLoadingPhaseLabel

export function meshChartLabel(chart: MeshChartKind): string {
  return MESH_CHART_LABELS[chart]
}

export function meshLoadingMessage(
  chart: MeshChartKind,
  phase: MeshLoadingPhase,
  error?: unknown,
): string {
  if (phase === 'ERROR') return toMeshChartError(error, `${meshChartLabel(chart)}加载失败`)
  return `${meshChartLabel(chart)}${meshLoadingPhaseLabel(phase)}`
}

export function toMeshChartError(reason: unknown, fallback = '图表加载失败'): string {
  if (reason instanceof Error && reason.message) return reason.message
  if (typeof reason === 'string' && reason.trim()) return reason
  return fallback
}

export function meshLoadingPhaseFromError(_reason: unknown): 'ERROR' {
  return 'ERROR'
}

export function meshLoadingPhaseFromRenderComplete(_payload: MeshChartRenderCompletePayload): 'COMPLETED' {
  return 'COMPLETED'
}

export function createInitialMeshLoadingState(
  chart: MeshChartKind,
  phase: MeshLoadingPhase = 'IDLE',
): MeshLoadingState {
  const updatedAt = new Date().toISOString()
  return {
    chart,
    phase,
    message: meshLoadingPhaseLabel(phase),
    updated_at: updatedAt,
  }
}

export const createMeshLoadingState = createInitialMeshLoadingState

export function meshLoadingStateFromRenderComplete(
  payload: MeshChartRenderCompletePayload,
): MeshLoadingState {
  return {
    chart: payload.chart,
    phase: 'COMPLETED',
    message: meshLoadingPhaseLabel('COMPLETED'),
    updated_at: payload.rendered_at,
  }
}

export function meshLoadingStateFromRenderError(
  payload: MeshChartRenderErrorPayload,
): MeshLoadingState {
  return {
    chart: payload.chart,
    phase: 'ERROR',
    message: payload.error,
    error: payload.error,
    updated_at: payload.failed_at,
  }
}
