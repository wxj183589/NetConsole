import type { BrowserWindow } from 'electron'

import type { RendererWorkloadReport } from '../shared/bridge'
import type { DesktopLogger } from './logger'

export type RendererSurface = 'main' | 'task-window' | 'workspace-window'

export interface RendererFailureActions {
  safeRecovery: boolean
  directRetry: boolean
  openLogs: boolean
}

export interface RendererProcessFailure {
  reason: string
  exitCode: number
  webContentsId: number
  surface: RendererSurface
  route: string
  occurredAt: string
  workload?: RendererWorkloadReport
  gpuRelated: boolean
  actions: RendererFailureActions
}

export interface RendererDiagnosticsOptions {
  logger: DesktopLogger
  canRetry: () => boolean
  surface?: RendererSurface
  getLatestWorkload?: () => RendererWorkloadReport | undefined
  hasRecentGpuFailure?: () => boolean
  onProcessGone?: (failure: RendererProcessFailure) => void
  showError: (
    title: string,
    detail: string,
    retryable: boolean,
    actions?: RendererFailureActions,
  ) => Promise<void>
  onLoadStarted?: () => void
  onLoadStopped?: () => void
}

export function installRendererDiagnostics(
  window: BrowserWindow,
  options: RendererDiagnosticsOptions,
): void {
  window.webContents.on('did-start-loading', () => {
    options.onLoadStarted?.()
    options.logger(
      'ELECTRON_RENDERER_LOAD_STARTED',
      `url=${safeDiagnosticUrl(window.webContents.getURL())}`,
    )
  })
  window.webContents.on('did-finish-load', () => {
    options.logger(
      'ELECTRON_RENDERER_LOAD_FINISHED',
      `url=${safeDiagnosticUrl(window.webContents.getURL())}`,
    )
  })
  window.webContents.on('did-stop-loading', () => {
    options.onLoadStopped?.()
    options.logger(
      'ELECTRON_RENDERER_LOAD_STOPPED',
      `url=${safeDiagnosticUrl(window.webContents.getURL())}`,
    )
  })
  window.webContents.on('console-message', (event) => {
    const details = event as unknown as { level?: string }
    if (details.level !== 'error') return
    options.logger('ELECTRON_RENDERER_CONSOLE_ERROR')
  })
  window.webContents.on('preload-error', () => {
    options.logger('ELECTRON_PRELOAD_FAILED')
    showFailure(
      options,
      'NetConsole 桌面桥接加载失败',
      '桌面安全桥接未能加载，请重试。',
    )
  })
  window.webContents.on(
    'did-fail-load',
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      options.logger(
        'ELECTRON_RENDERER_LOAD_FAILED',
        `code=${errorCode} main_frame=${isMainFrame} url=${safeDiagnosticUrl(validatedURL)}`,
      )
      if (isMainFrame && errorCode !== -3) {
        showFailure(options, 'NetConsole 页面加载失败', errorDescription)
      }
    },
  )
  window.webContents.on('render-process-gone', (_event, details) => {
    const workload = options.getLatestWorkload?.()
    const failure = buildRendererProcessFailure({
      reason: details.reason,
      exitCode: details.exitCode,
      webContentsId: window.webContents.id,
      surface: options.surface ?? 'main',
      route: workload?.route ?? safeDiagnosticRoute(window.webContents.getURL()),
      workload,
      gpuRelated: options.hasRecentGpuFailure?.() ?? false,
    })
    options.logger('ELECTRON_RENDERER_PROCESS_GONE', rendererFailureLogDetail(failure))
    options.onProcessGone?.(failure)
    showFailure(
      options,
      'NetConsole 页面异常退出',
      rendererFailurePageDetail(failure),
      failure.actions,
    )
  })
  window.on('unresponsive', () => {
    options.logger('ELECTRON_RENDERER_UNRESPONSIVE')
    showFailure(options, 'NetConsole 页面无响应', '页面暂时无响应，请重试。')
  })
  window.on('responsive', () => options.logger('ELECTRON_RENDERER_RESPONSIVE'))
}

export function safeDiagnosticUrl(value: string): string {
  try {
    const url = new URL(value)
    if (url.protocol === 'http:' && url.hostname === '127.0.0.1') {
      return `${url.origin}${diagnosticRoute(url.pathname)}`
    }
    return url.protocol
  } catch {
    return 'invalid:'
  }
}

export function safeDiagnosticRoute(value: string): string {
  try {
    return diagnosticRoute(new URL(value).pathname)
  } catch {
    return '/other'
  }
}

export function buildRendererProcessFailure(input: {
  reason: unknown
  exitCode: unknown
  webContentsId: unknown
  surface: RendererSurface
  route: string
  workload?: RendererWorkloadReport
  gpuRelated?: boolean
  occurredAt?: string
}): RendererProcessFailure {
  const reason = safeGoneReason(input.reason)
  const exitCode = Number.isSafeInteger(input.exitCode) ? Number(input.exitCode) : -1
  const webContentsId = Number.isSafeInteger(input.webContentsId) && Number(input.webContentsId) >= 0
    ? Number(input.webContentsId)
    : -1
  const trackside = input.workload?.module === 'mesh-analysis'
    && isTracksidePhase(input.workload.phase)
  return {
    reason,
    exitCode,
    webContentsId,
    surface: input.surface,
    route: safeRoute(input.route),
    occurredAt: input.occurredAt ?? new Date().toISOString(),
    ...(input.workload ? { workload: input.workload } : {}),
    gpuRelated: Boolean(input.gpuRelated),
    actions: {
      safeRecovery: trackside,
      directRetry: true,
      openLogs: true,
    },
  }
}

export function rendererFailureLogDetail(failure: RendererProcessFailure): string {
  const workload = failure.workload
  return [
    `reason=${failure.reason}`,
    `exit_code=${failure.exitCode}`,
    `web_contents_id=${failure.webContentsId}`,
    `surface=${failure.surface}`,
    `route=${failure.route}`,
    `occurred_at=${failure.occurredAt}`,
    `gpu_related=${failure.gpuRelated}`,
    `trackside_rendering=${workload ? isTracksidePhase(workload.phase) : false}`,
    ...(workload ? [
      `module=${workload.module}`,
      `session_id=${workload.sessionId ?? 'none'}`,
      `source_file_id=${workload.sourceFileId ?? 'none'}`,
      `radio=${workload.radio ?? 'none'}`,
      `phase=${workload.phase}`,
      `series_count=${workload.seriesCount ?? 'none'}`,
      `point_count=${workload.pointCount ?? 'none'}`,
      `metadata_count=${workload.metadataCount ?? 'none'}`,
      `conflict_edge_count=${workload.conflictEdgeCount ?? 'none'}`,
      `mesh_instances=${workload.meshInstanceCount ?? 'none'}`,
      `trackside_caches=${workload.tracksideCacheCount ?? 'none'}`,
      `trackside_charts=${workload.tracksideChartCount ?? 'none'}`,
      `active_detail_requests=${workload.activeDetailRequests ?? 'none'}`,
      `cache_builds=${workload.tracksideCacheBuildCount ?? 'none'}`,
      `cache_disposes=${workload.tracksideCacheDisposeCount ?? 'none'}`,
      `echarts_inits=${workload.chartInitCount ?? 'none'}`,
      `echarts_disposes=${workload.chartDisposeCount ?? 'none'}`,
      `canvas_count=${workload.canvasCount ?? 'none'}`,
      `returned_link_points=${workload.returnedLinkPoints ?? 'none'}`,
      `returned_frames=${workload.returnedFrames ?? 'none'}`,
      `heap_used_mb=${bytesToMb(workload.heapUsedBytes)}`,
      `heap_total_mb=${bytesToMb(workload.heapTotalBytes)}`,
      `heap_limit_mb=${bytesToMb(workload.heapLimitBytes)}`,
      `report_revision=${workload.reportRevision}`,
    ] : []),
  ].join(' ')
}

export function rendererFailurePageDetail(failure: RendererProcessFailure): string {
  const workload = failure.workload
  const moduleLabel = workload?.module === 'mesh-analysis'
    ? 'MR 原始 MESH 日志分析'
    : '未知模块'
  const rendererReasonLabel = ({
    oom: '内存不足',
    crashed: 'Renderer 崩溃',
    killed: 'Renderer 被系统终止',
    'abnormal-exit': 'Renderer 异常退出',
    'launch-failed': 'Renderer 启动失败',
    'integrity-failure': 'Renderer 完整性校验失败',
    'clean-exit': 'Renderer 已退出',
  } as Record<string, string>)[failure.reason] ?? '未知'
  const reasonLabel = failure.gpuRelated
    ? `${rendererReasonLabel}（此前检测到 GPU 进程异常）`
    : rendererReasonLabel
  return [
    `原因：${reasonLabel}`,
    `出错模块：${moduleLabel}`,
    `分析会话：${shortSafeId(workload?.sessionId)}`,
    `来源 / Radio：${workload?.sourceFileId ?? '—'} / ${workload?.radio ?? '—'}`,
    `渲染阶段：${phaseLabel(workload?.phase)}`,
    `错误代码：${failure.exitCode}`,
    failure.actions.safeRecovery
      ? '建议操作：优先使用安全恢复；该模式不会自动重新加载轨旁信号图。'
      : '建议操作：重试页面；如果问题持续，请打开日志目录。',
  ].join('\n')
}

function diagnosticRoute(pathname: string): string {
  const parts = pathname.split('/').filter(Boolean)
  if (parts[0] === 'rail-transit' && parts[1] === 'mesh-analysis') {
    return '/rail-transit/mesh-analysis'
  }
  const segment = parts[0] ?? ''
  if (!segment) return '/'
  if (new Set([
    'ac-management',
    'agents',
    'api',
    'command-reference',
    'config-center',
    'feature-flags',
    'file-manager',
    'logs',
    'network',
    'network-tools',
    'rail-transit',
    'settings',
    'tasks',
    'ws',
  ]).has(segment)) {
    return `/${segment}`
  }
  return '/other'
}

function showFailure(
  options: RendererDiagnosticsOptions,
  title: string,
  detail: string,
  actions?: RendererFailureActions,
): void {
  if (!options.canRetry()) return
  const operation = actions
    ? options.showError(title, detail, true, actions)
    : options.showError(title, detail, true)
  void operation.catch(() => {
    options.logger('ELECTRON_RENDERER_ERROR_PAGE_FAILED')
  })
}

function isTracksidePhase(phase: RendererWorkloadReport['phase']): boolean {
  return phase !== 'session-selected' && phase !== 'chart-disposed'
}

function safeGoneReason(value: unknown): string {
  const reason = typeof value === 'string' ? value : ''
  return new Set([
    'clean-exit',
    'abnormal-exit',
    'killed',
    'crashed',
    'oom',
    'launch-failed',
    'integrity-failure',
  ]).has(reason) ? reason : 'unknown'
}

function safeRoute(value: string): string {
  return value === '/rail-transit/mesh-analysis'
    ? value
    : diagnosticRoute(value.startsWith('/') ? value : '/other')
}

function phaseLabel(phase: RendererWorkloadReport['phase'] | undefined): string {
  return ({
    'session-selected': '分析会话已选择',
    'trackside-request-started': '轨旁信号图请求',
    'trackside-response-received': '轨旁信号图响应',
    'trackside-cache-building': '轨旁信号图缓存构建',
    'trackside-cache-ready': '轨旁信号图缓存就绪',
    'echarts-init': '轨旁信号图初始化',
    'echarts-set-option': '轨旁信号图数据装载',
    'echarts-interactive': '轨旁信号图交互稳定',
    'chart-disposed': '轨旁信号图已释放',
  } as Record<string, string>)[phase ?? ''] ?? '未知'
}

function shortSafeId(value: string | undefined): string {
  if (!value) return '—'
  return value.length <= 48 ? value : `${value.slice(0, 20)}…${value.slice(-12)}`
}

function bytesToMb(value: number | undefined): string {
  return value == null ? 'none' : (value / 1024 / 1024).toFixed(1)
}
