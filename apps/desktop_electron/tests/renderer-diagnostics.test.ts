import type { BrowserWindow } from 'electron'
import { describe, expect, it, vi } from 'vitest'

import {
  buildRendererProcessFailure,
  installRendererDiagnostics,
  rendererFailureLogDetail,
  rendererFailurePageDetail,
  safeDiagnosticUrl,
} from '../src/main/renderer-diagnostics'

describe('renderer diagnostics', () => {
  it('shows a retryable error state for main-frame load failures', async () => {
    const webListeners = new Map<string, (...args: unknown[]) => void>()
    const windowListeners = new Map<string, (...args: unknown[]) => void>()
    const logger = vi.fn()
    const showError = vi.fn(async () => undefined)
    const onLoadStarted = vi.fn()
    const onLoadStopped = vi.fn()
    const window = {
      webContents: {
        getURL: () => 'http://127.0.0.1:5173/tasks?session_token=secret',
        on: vi.fn((event, handler) => webListeners.set(event, handler)),
      },
      on: vi.fn((event, handler) => windowListeners.set(event, handler)),
    } as unknown as BrowserWindow
    installRendererDiagnostics(window, {
      logger,
      canRetry: () => true,
      showError,
      onLoadStarted,
      onLoadStopped,
    })
    webListeners.get('did-start-loading')?.()
    webListeners.get('did-stop-loading')?.()
    const didFailLoad = webListeners.get('did-fail-load') as (
      event: unknown,
      code: number,
      description: string,
      url: string,
      mainFrame: boolean,
    ) => void

    didFailLoad({}, -105, '连接失败', 'http://127.0.0.1:5173/api/files?token=secret', true)
    await Promise.resolve()

    expect(showError).toHaveBeenCalledWith(
      'NetConsole 页面加载失败',
      '连接失败',
      true,
    )
    expect(JSON.stringify(logger.mock.calls)).not.toContain('token=secret')
    expect(onLoadStarted).toHaveBeenCalledOnce()
    expect(onLoadStopped).toHaveBeenCalledOnce()
  })

  it('records OOM exitCode and the latest safe workload before offering safe recovery', async () => {
    const webListeners = new Map<string, (...args: unknown[]) => void>()
    const logger = vi.fn()
    const showError = vi.fn(async (
      _title: string,
      _detail: string,
      _retry: boolean,
      _actions?: { safeRecovery?: boolean; directRetry?: boolean; openLogs?: boolean },
    ) => undefined)
    const onProcessGone = vi.fn()
    const window = {
      webContents: {
        id: 17,
        getURL: () => 'http://127.0.0.1:5173/',
        on: vi.fn((event, handler) => webListeners.set(event, handler)),
      },
      on: vi.fn(),
    } as unknown as BrowserWindow
    installRendererDiagnostics(window, {
      logger,
      canRetry: () => true,
      showError,
      surface: 'main',
      getLatestWorkload: () => ({
        module: 'mesh-analysis',
        route: '/rail-transit/mesh-analysis',
        phase: 'echarts-set-option',
        sessionId: 'session-1',
        sourceFileId: 9,
        radio: 1,
        returnedFrames: 18_188,
        returnedLinkPoints: 44_251,
        seriesCount: 770,
        heapUsedBytes: 512 * 1024 * 1024,
        heapLimitBytes: 1024 * 1024 * 1024,
        reportRevision: 8,
      }),
      onProcessGone,
    })
    const didFailLoad = webListeners.get('did-fail-load') as (
      event: unknown,
      code: number,
      description: string,
      url: string,
      mainFrame: boolean,
    ) => void
    const processGone = webListeners.get('render-process-gone') as (
      event: unknown,
      details: { reason: string; exitCode: number },
    ) => void

    didFailLoad({}, -3, 'aborted', 'http://127.0.0.1:5173/', true)
    expect(showError).not.toHaveBeenCalled()
    processGone({}, { reason: 'oom', exitCode: 137 })
    await Promise.resolve()
    expect(showError).toHaveBeenCalledWith(
      'NetConsole 页面异常退出',
      expect.stringContaining('原因：内存不足'),
      true,
      {
        safeRecovery: true,
        directRetry: true,
        openLogs: true,
      },
    )
    expect(showError.mock.calls[0]?.[1]).toContain('渲染阶段：轨旁信号图数据装载')
    expect(logger).toHaveBeenCalledWith(
      'ELECTRON_RENDERER_PROCESS_GONE',
      expect.stringMatching(/reason=oom exit_code=137 web_contents_id=17.*trackside_rendering=true/),
    )
    expect(JSON.stringify(logger.mock.calls)).not.toContain('token')
    expect(onProcessGone).toHaveBeenCalledWith(expect.objectContaining({
      reason: 'oom',
      exitCode: 137,
      webContentsId: 17,
    }))
  })

  it('classifies Renderer crash separately from a recent GPU failure', () => {
    const crashed = buildRendererProcessFailure({
      reason: 'crashed',
      exitCode: -1073741819,
      webContentsId: 9,
      surface: 'main',
      route: '/rail-transit/mesh-analysis',
      occurredAt: '2026-07-23T10:00:00.000Z',
      gpuRelated: false,
    })
    const gpuRelated = { ...crashed, gpuRelated: true }

    expect(rendererFailurePageDetail(crashed)).toContain('原因：Renderer 崩溃')
    expect(rendererFailurePageDetail(gpuRelated)).toContain('原因：Renderer 崩溃（此前检测到 GPU 进程异常）')
    expect(rendererFailureLogDetail(crashed)).toContain('gpu_related=false')
  })

  it('replaces a preload failure with a retryable safe status page', async () => {
    const webListeners = new Map<string, (...args: unknown[]) => void>()
    const logger = vi.fn()
    const showError = vi.fn(async () => undefined)
    const window = {
      webContents: {
        getURL: () => 'http://127.0.0.1:5173/',
        on: vi.fn((event, handler) => webListeners.set(event, handler)),
      },
      on: vi.fn(),
    } as unknown as BrowserWindow
    installRendererDiagnostics(window, {
      logger,
      canRetry: () => true,
      showError,
    })

    webListeners.get('preload-error')?.({}, 'C:\\private\\preload.cjs', new Error('secret'))
    await Promise.resolve()

    expect(showError).toHaveBeenCalledWith(
      'NetConsole 桌面桥接加载失败',
      '桌面安全桥接未能加载，请重试。',
      true,
    )
    expect(JSON.stringify(logger.mock.calls)).not.toContain('C:\\private')
    expect(JSON.stringify(logger.mock.calls)).not.toContain('secret')
  })

  it('ignores subframe failures and records unresponsive recovery safely', async () => {
    const webListeners = new Map<string, (...args: unknown[]) => void>()
    const windowListeners = new Map<string, (...args: unknown[]) => void>()
    const logger = vi.fn()
    const showError = vi.fn(async () => {
      throw new Error('status page failed')
    })
    const window = {
      webContents: {
        getURL: () => 'http://127.0.0.1:5173/',
        on: vi.fn((event, handler) => webListeners.set(event, handler)),
      },
      on: vi.fn((event, handler) => windowListeners.set(event, handler)),
    } as unknown as BrowserWindow
    installRendererDiagnostics(window, {
      logger,
      canRetry: () => true,
      showError,
    })

    webListeners.get('did-fail-load')?.({}, -105, 'failed', 'https://example.com/frame', false)
    expect(showError).not.toHaveBeenCalled()
    windowListeners.get('unresponsive')?.()
    windowListeners.get('responsive')?.()
    await Promise.resolve()
    await Promise.resolve()

    expect(showError).toHaveBeenCalledWith(
      'NetConsole 页面无响应',
      '页面暂时无响应，请重试。',
      true,
    )
    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_RESPONSIVE')
    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_ERROR_PAGE_FAILED')
  })

  it('logs only trusted loopback origin and path', () => {
    expect(safeDiagnosticUrl('http://127.0.0.1:43123/api/health?token=secret')).toBe(
      'http://127.0.0.1:43123/api',
    )
    expect(safeDiagnosticUrl('http://127.0.0.1:5173/tasks/runtime-secret')).toBe(
      'http://127.0.0.1:5173/tasks',
    )
    expect(safeDiagnosticUrl('http://127.0.0.1:5173/%72%75%6e%74%69%6d%65-secret')).toBe(
      'http://127.0.0.1:5173/other',
    )
    expect(safeDiagnosticUrl('https://example.com/private?q=1')).toBe('https:')
  })

  it('never copies renderer console text into desktop logs', () => {
    const webListeners = new Map<string, (...args: unknown[]) => void>()
    const logger = vi.fn()
    const window = {
      webContents: {
        getURL: () => 'http://127.0.0.1:5173/',
        on: vi.fn((event, handler) => webListeners.set(event, handler)),
      },
      on: vi.fn(),
    } as unknown as BrowserWindow
    installRendererDiagnostics(window, {
      logger,
      canRetry: () => true,
      showError: vi.fn(async () => undefined),
    })

    webListeners.get('console-message')?.({
      level: 'error',
      message: 'X-NetConsole-Session: bare-runtime-token',
    })

    expect(logger).toHaveBeenCalledWith('ELECTRON_RENDERER_CONSOLE_ERROR')
    expect(JSON.stringify(logger.mock.calls)).not.toContain('bare-runtime-token')
  })
})
