import type { BrowserWindow } from 'electron'

import type { DesktopLogger } from './logger'

export interface RendererDiagnosticsOptions {
  logger: DesktopLogger
  canRetry: () => boolean
  showError: (title: string, detail: string, retryable: boolean) => Promise<void>
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
    options.logger('ELECTRON_RENDERER_PROCESS_GONE', `reason=${details.reason}`)
    showFailure(options, 'NetConsole 页面异常退出', '渲染进程已退出，请重试。')
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

function diagnosticRoute(pathname: string): string {
  const segment = pathname.split('/').filter(Boolean)[0] ?? ''
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
): void {
  if (!options.canRetry()) return
  void options.showError(title, detail, true).catch(() => {
    options.logger('ELECTRON_RENDERER_ERROR_PAGE_FAILED')
  })
}
