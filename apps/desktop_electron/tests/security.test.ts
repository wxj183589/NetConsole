import type { BrowserWindow } from 'electron'
import { describe, expect, it, vi } from 'vitest'

import {
  contentSecurityPolicy,
  desktopSessionCookiePath,
  installWindowSecurity,
  isAllowedNavigation,
  isTrustedRendererSender,
  secureWebPreferences,
} from '../src/main/security'
import {
  MANAGED_RENDERER_RETRY_ACTION,
  ManagedRendererRetryNavigation,
} from '../src/main/renderer-theme-display-gate'
import {
  validateArtifactFileName,
  validateBackendDownloadRequest,
} from '../src/shared/validation'

describe('Electron security policy', () => {
  it('disables DevTools in production while preserving the development workflow', () => {
    const production = secureWebPreferences('preload.cjs', false)
    const development = secureWebPreferences('preload.cjs', true)

    expect(production.devTools).toBe(false)
    expect(development.devTools).toBe(true)
    expect(production).toMatchObject({
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
    })
  })

  it('keeps the exact normalized Artifact extension for save-type matching', () => {
    expect(validateArtifactFileName('固件.bin')).toBe('.bin')
    expect(validateArtifactFileName('startup.conf')).toBe('.conf')
    expect(validateArtifactFileName('无扩展')).toBe('<none>')
    expect(validateArtifactFileName('.env')).toBe('<none>')
    expect(validateArtifactFileName('capture.vendor-format')).toBe('.vendor-format')
    expect(validateArtifactFileName('archive.tar.gz')).toBe('.tar.gz')
    expect(validateArtifactFileName('archive.zip.gz')).toBe('.zip.gz')
    expect(validateArtifactFileName('capture.other-format')).not.toBe(
      validateArtifactFileName('capture.vendor-format'),
    )
  })

  it('accepts only formal Artifact download endpoints and endpoint-specific query fields', () => {
    const approved = [
      ['/api/device-management/exports/task-1/download', { artifact_id: 'artifact-1' }],
      ['/api/config-collection/artifacts/artifact-1', undefined],
      ['/api/file-management/downloads/task-1/file', { site_id: 'demo' }],
      ['/api/ac-management/extensions/artifacts/artifact-1/download', undefined],
      ['/api/ac-management/fit-aps/omnipeek/artifacts/artifact-1/download', undefined],
      ['/api/ac-management/fit-aps/artifacts/artifact-1/download', undefined],
      ['/api/rail-transit/mesh-analysis/sessions/session-1/artifacts/artifact-1/download', undefined],
      ['/api/rail-transit/mesh-analysis/sessions/%E4%BC%9A%E8%AF%9D%2F1/artifacts/%E6%8A%A5%E5%91%8A%2F1/download', undefined],
      ['/api/rail-transit/trackside-ap-business/artifacts/artifact-1/download', undefined],
      ['/api/rail-transit/base-data/station-template', undefined],
      ['/api/rail-transit/base-data/station-template-export', { site_id: 'demo' }],
      ['/api/online-mr/report-artifacts/artifact-1/download', undefined],
      ['/api/rail-transit/mesh-analysis/report-artifacts/artifact-1/download', undefined],
      ['/api/network-tools/artifacts/artifact-1', undefined],
      ['/api/network-tools/wireless-scan/artifacts/artifact-1', undefined],
      ['/api/command-reference/artifacts/artifact-1/download', undefined],
      ['/api/system-maintenance/artifacts/open_source_txt/artifact-1', undefined],
      ['/api/job-center/artifacts/artifact-1', undefined],
    ] as const
    for (const [apiPath, query] of approved) {
      expect(validateBackendDownloadRequest({ apiPath, query, suggestedName: '报告.zip' })).toMatchObject({ apiPath })
    }

    expect(() => validateBackendDownloadRequest({
      apiPath: '/api/health',
      suggestedName: 'health.json',
    })).toThrow('approved Artifact download endpoint')
    expect(() => validateBackendDownloadRequest({
      apiPath: '/api/config-collection/artifacts/artifact-1',
      query: { site_id: 'demo' },
      suggestedName: '配置.zip',
    })).toThrow('approved Artifact download endpoint')
    expect(() => validateBackendDownloadRequest({
      apiPath: '/api/device-management/exports/task-1/download',
      suggestedName: '设备.csv',
    })).toThrow('approved Artifact download endpoint')
  })

  it('limits the development cookie to WebSocket paths and authenticates production assets', () => {
    expect(desktopSessionCookiePath(true)).toBe('/ws')
    expect(desktopSessionCookiePath(false)).toBe('/')
  })

  it('keeps production script policy free of eval and limits connections to loopback origins', () => {
    const policy = contentSecurityPolicy(false, [
      'http://127.0.0.1:43123',
      'https://example.com',
    ])

    expect(policy).toContain("script-src 'self'")
    expect(policy).not.toContain('unsafe-eval')
    expect(policy).toContain('http://127.0.0.1:43123')
    expect(policy).toContain('ws://127.0.0.1:43123')
    expect(policy).not.toContain('example.com')
    expect(policy).toContain("object-src 'none'")
    expect(policy).toContain("frame-ancestors 'none'")
  })

  it('allows navigation only inside an explicitly registered loopback origin', () => {
    const origins = ['http://127.0.0.1:5173']
    expect(isAllowedNavigation('http://127.0.0.1:5173/tasks', origins)).toBe(true)
    expect(isAllowedNavigation('http://127.0.0.1:5174/tasks', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/api/health', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/ws/tasks', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/%61pi/health', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/api%2Fhealth', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/%5F%5Fdesktop_session', origins)).toBe(false)
    expect(isAllowedNavigation('http://127.0.0.1:5173/__desktop_session', origins)).toBe(false)
    expect(isAllowedNavigation('https://example.com', origins)).toBe(false)
    expect(isAllowedNavigation('file:///C:/Windows/System32/calc.exe', origins)).toBe(false)
  })

  it('prevents backend navigation without changing the current renderer page', () => {
    const listeners = new Map<string, (...args: unknown[]) => void>()
    const sessionListeners = new Map<string, (...args: unknown[]) => void>()
    let openHandler: ((details: { url: string }) => { action: 'deny' }) | undefined
    const blocked = vi.fn()
    const window = {
      webContents: {
        setWindowOpenHandler: vi.fn((handler) => { openHandler = handler }),
        on: vi.fn((event, handler) => listeners.set(event, handler)),
        session: {
          on: vi.fn((event, handler) => sessionListeners.set(event, handler)),
          setPermissionCheckHandler: vi.fn(),
          setPermissionRequestHandler: vi.fn(),
          webRequest: { onHeadersReceived: vi.fn() },
        },
      },
    } as unknown as BrowserWindow
    installWindowSecurity(
      window,
      () => ['http://127.0.0.1:5173'],
      () => ['http://127.0.0.1:5173', 'http://127.0.0.1:43123'],
      true,
      blocked,
      blocked,
    )
    const navigate = listeners.get('will-navigate') as (
      event: { preventDefault(): void },
      target: string,
    ) => void
    const redirect = listeners.get('will-redirect') as (
      event: { preventDefault(): void },
      target: string,
    ) => void
    const backendEvent = { preventDefault: vi.fn() }
    const redirectEvent = { preventDefault: vi.fn() }
    const pageEvent = { preventDefault: vi.fn() }
    const downloadEvent = { preventDefault: vi.fn() }

    navigate(backendEvent, 'http://127.0.0.1:5173/api/file-management/downloads/task/file')
    redirect(redirectEvent, 'http://127.0.0.1:43123/api/health')
    navigate(pageEvent, 'http://127.0.0.1:5173/tasks')
    sessionListeners.get('will-download')?.(downloadEvent)

    expect(backendEvent.preventDefault).toHaveBeenCalledOnce()
    expect(redirectEvent.preventDefault).toHaveBeenCalledOnce()
    expect(pageEvent.preventDefault).not.toHaveBeenCalled()
    expect(downloadEvent.preventDefault).toHaveBeenCalledOnce()
    expect(openHandler?.({ url: 'https://example.com' })).toEqual({ action: 'deny' })
    expect(blocked).toHaveBeenCalledTimes(4)
  })

  it('keeps the security guard while allowing one Main-managed retry action', async () => {
    const listeners = new Map<string, Array<(...args: unknown[]) => void>>()
    const currentUrl = 'data:text/html;charset=utf-8,managed-error'
    const blocked = vi.fn()
    const retry = vi.fn(async () => undefined)
    const window = {
      isDestroyed: vi.fn(() => false),
      webContents: {
        getURL: vi.fn(() => currentUrl),
        setWindowOpenHandler: vi.fn(),
        on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
          listeners.set(event, [...(listeners.get(event) ?? []), handler])
        }),
        session: {
          on: vi.fn(),
          setPermissionCheckHandler: vi.fn(),
          setPermissionRequestHandler: vi.fn(),
          webRequest: { onHeadersReceived: vi.fn() },
        },
      },
    } as unknown as BrowserWindow
    installWindowSecurity(
      window,
      () => ['http://127.0.0.1:5173'],
      () => ['http://127.0.0.1:5173'],
      true,
      blocked,
    )
    const navigation = new ManagedRendererRetryNavigation(window, retry)
    navigation.armForStatusPage(currentUrl)
    const event = { preventDefault: vi.fn() }

    for (const listener of listeners.get('will-navigate') ?? []) {
      listener(event, MANAGED_RENDERER_RETRY_ACTION)
    }
    await vi.waitFor(() => expect(retry).toHaveBeenCalledOnce())

    expect(listeners.get('will-navigate')).toHaveLength(2)
    expect(event.preventDefault).toHaveBeenCalledTimes(2)
    expect(blocked).toHaveBeenCalledWith(MANAGED_RENDERER_RETRY_ACTION)
  })

  it('trusts only the current main frame at an allowed origin for IPC', () => {
    const mainFrame = { url: 'http://127.0.0.1:5173/tasks' }
    const webContents = { mainFrame }
    const window = { webContents }
    const origins = ['http://127.0.0.1:5173']

    expect(isTrustedRendererSender({ sender: webContents, senderFrame: mainFrame }, window, origins)).toBe(true)
    expect(isTrustedRendererSender({ sender: webContents, senderFrame: { url: mainFrame.url } }, window, origins)).toBe(false)
    mainFrame.url = 'https://example.com/'
    expect(isTrustedRendererSender({ sender: webContents, senderFrame: mainFrame }, window, origins)).toBe(false)
  })
})
