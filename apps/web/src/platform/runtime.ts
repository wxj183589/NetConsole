import { createBrowserAdapter } from './browser-adapter'
import { createElectronAdapter } from './electron-adapter'
import type { ActiveRuntimeConfig, PlatformAdapter } from './types'
import type {
  BackendStatus,
  BackendDownloadRequest,
  BackendDownloadResult,
} from '../../../desktop_electron/src/shared/bridge'

const browserApiBase = import.meta.env.VITE_API_BASE || ''
const browserDevelopmentToken = import.meta.env.DEV
  ? import.meta.env.VITE_DEV_SESSION_TOKEN || ''
  : ''
const RUNTIME_REBIND_READY_TIMEOUT_MS = 5_000

let adapter: PlatformAdapter = createBrowserAdapter(browserApiBase, browserDevelopmentToken)
let config: ActiveRuntimeConfig = {
  hostType: 'browser',
  apiBaseUrl: browserApiBase.trim().replace(/\/+$/, ''),
  apiToken: '',
}
let initializationState: 'uninitialized' | 'initializing' | 'ready' | 'failed' = 'uninitialized'
let runtimeGeneration = 0
let runtimeLifecycle = 0
let runtimeStatus: BackendStatus = { state: 'starting' }
let supervisorStatus: BackendStatus = { state: 'starting' }
let supervisorStatusRevision = 0
let removeBackendStatusListener: (() => void) | undefined
let rebindPromise: Promise<ActiveRuntimeConfig> | undefined
const runtimeStatusListeners = new Set<(status: BackendStatus) => void>()
const supervisorReadyWaiters = new Set<() => void>()

export async function initializePlatformRuntime(): Promise<ActiveRuntimeConfig> {
  const lifecycle = ++runtimeLifecycle
  removeBackendStatusListener?.()
  removeBackendStatusListener = undefined
  initializationState = 'initializing'
  try {
    const expectedElectronHost = isElectronHostExpected()
    if (expectedElectronHost && !window.netconsoleDesktop) {
      logPlatformDiagnostic('PLATFORM_RUNTIME_INITIALIZED', {
        host: 'electron',
        bridge: false,
        generation: 0,
      })
      throw new Error('Electron 文件保存组件未加载，请完全退出 NetConsole 后重新启动。')
    }
    const nextAdapter = window.netconsoleDesktop
      ? createElectronAdapter(window.netconsoleDesktop)
      : createBrowserAdapter(browserApiBase, browserDevelopmentToken)
    const runtime = await nextAdapter.getRuntimeConfig()
    if (lifecycle !== runtimeLifecycle) throw new Error('Platform runtime initialization was superseded')
    const nextConfig: ActiveRuntimeConfig = {
      ...runtime,
      apiBaseUrl: normalizeApiBase(runtime.apiBaseUrl),
      hostType: nextAdapter.hostType,
    }
    adapter = nextAdapter
    config = nextConfig
    runtimeGeneration = 1
    supervisorStatus = { state: 'ready', ...(config.apiBaseUrl ? { baseUrl: config.apiBaseUrl } : {}) }
    supervisorStatusRevision += 1
    setRuntimeStatus(supervisorStatus)
    logPlatformDiagnostic(
      'PLATFORM_RUNTIME_INITIALIZED',
      { host: adapter.hostType, bridge: Boolean(window.netconsoleDesktop), generation: runtimeGeneration },
    )
    initializationState = 'ready'
    removeBackendStatusListener = adapter.onBackendStatusChanged(handleBackendStatusChanged)
    return { ...config }
  } catch (cause) {
    initializationState = 'failed'
    throw cause
  }
}

export async function refreshPlatformRuntimeConfig(reason = 'api_recovery'): Promise<ActiveRuntimeConfig> {
  assertElectronRuntimeReady()
  if (adapter.hostType !== 'electron') return { ...config }
  if (rebindPromise) return rebindPromise
  const lifecycle = runtimeLifecycle
  const oldConfig = config
  const oldGeneration = runtimeGeneration
  const startedAt = performance.now()
  setRuntimeStatus({ state: 'starting' })
  logPlatformDiagnostic('PLATFORM_RUNTIME_REBIND_STARTED', {
    host: 'electron',
    reason,
    old_generation: oldGeneration,
  })
  const currentPromise = ensureSupervisorReady()
    .then(() => adapter.getRuntimeConfig())
    .then((runtime) => {
      if (lifecycle !== runtimeLifecycle) throw new Error('Platform runtime rebind was superseded')
      if (supervisorStatus.state !== 'ready') throw new Error('Electron Backend is not ready')
      const nextConfig: ActiveRuntimeConfig = {
        ...runtime,
        apiBaseUrl: normalizeApiBase(runtime.apiBaseUrl),
        hostType: 'electron',
      }
      config = nextConfig
      runtimeGeneration = oldGeneration + 1
      setRuntimeStatus({ state: 'ready', baseUrl: nextConfig.apiBaseUrl })
      logPlatformDiagnostic('PLATFORM_RUNTIME_REBIND_COMPLETED', {
        host: 'electron',
        reason,
        old_generation: oldGeneration,
        new_generation: runtimeGeneration,
        port_changed: runtimePort(oldConfig.apiBaseUrl) !== runtimePort(nextConfig.apiBaseUrl),
        duration_ms: Math.round(performance.now() - startedAt),
      })
      return { ...config }
    })
    .catch((cause) => {
      if (lifecycle === runtimeLifecycle) setRuntimeStatus({ state: 'failed', error: 'Renderer runtime rebind failed' })
      logPlatformDiagnostic('PLATFORM_RUNTIME_REBIND_FAILED', {
        host: 'electron',
        reason,
        old_generation: oldGeneration,
        duration_ms: Math.round(performance.now() - startedAt),
      })
      throw cause
    })
    .finally(() => {
      if (rebindPromise === currentPromise) rebindPromise = undefined
    })
  rebindPromise = currentPromise
  return currentPromise
}

export function getPlatformAdapter(): PlatformAdapter {
  return adapter
}

export function getRuntimeConfig(): ActiveRuntimeConfig {
  return { ...config }
}

export function getPlatformRuntimeStatus(): BackendStatus {
  return { ...runtimeStatus }
}

export function onPlatformRuntimeStatusChanged(listener: (status: BackendStatus) => void): () => void {
  runtimeStatusListeners.add(listener)
  return () => runtimeStatusListeners.delete(listener)
}

export function resolveApiUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('API path must start with /')
  assertElectronRuntimeReady()
  return config.apiBaseUrl ? `${config.apiBaseUrl}${path}` : path
}

export function resolveWebSocketUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('WebSocket path must start with /')
  assertElectronRuntimeReady()
  const locationOrigin = window.location.origin
    || `${window.location.protocol}//${window.location.host}`
  const httpUrl = config.apiBaseUrl
    ? `${config.apiBaseUrl}${path}`
    : new URL(path, `${locationOrigin}/`).toString()
  const url = new URL(httpUrl, `${locationOrigin}/`)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export function resolveFrontendAssetUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('asset path must start with /')
  assertElectronRuntimeReady()
  if (config.hostType === 'electron' && config.apiBaseUrl) {
    return `${config.apiBaseUrl}${path}`
  }
  return path
}

export function downloadBackendResource(
  request: BackendDownloadRequest,
): Promise<BackendDownloadResult> {
  assertElectronRuntimeReady()
  return adapter.downloadBackendResource(request)
}

export function resetPlatformRuntimeForTests(apiBaseUrl = '', initialized = true): void {
  runtimeLifecycle += 1
  for (const waiter of [...supervisorReadyWaiters]) waiter()
  removeBackendStatusListener?.()
  removeBackendStatusListener = undefined
  rebindPromise = undefined
  adapter = createBrowserAdapter(apiBaseUrl)
  config = { hostType: 'browser', apiBaseUrl: normalizeApiBase(apiBaseUrl), apiToken: '' }
  initializationState = initialized ? 'ready' : 'uninitialized'
  runtimeGeneration = initialized ? 1 : 0
  supervisorStatus = { state: initialized ? 'ready' : 'starting' }
  supervisorStatusRevision += 1
  runtimeStatus = { ...supervisorStatus }
  runtimeStatusListeners.clear()
}

function assertElectronRuntimeReady(): void {
  if (initializationState === 'ready') return
  if (isElectronHostExpected()) {
    throw new Error('Electron 文件保存组件未加载，请完全退出 NetConsole 后重新启动。')
  }
  if (typeof window !== 'undefined' && window.netconsoleDesktop) {
    throw new Error('Electron 运行时尚未就绪，拒绝回退到相对 API 地址')
  }
}

function isElectronHostExpected(): boolean {
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search || '').get('netconsole_host') === 'electron'
}

function handleBackendStatusChanged(status: BackendStatus): void {
  supervisorStatus = { ...status }
  supervisorStatusRevision += 1
  if (status.state === 'ready') {
    for (const waiter of [...supervisorReadyWaiters]) waiter()
    setRuntimeStatus({ state: 'starting' })
    void refreshPlatformRuntimeConfig('backend_ready').catch(() => undefined)
    return
  }
  setRuntimeStatus(status)
}

async function ensureSupervisorReady(): Promise<void> {
  const requestedAtRevision = supervisorStatusRevision
  const latestStatus = await adapter.getBackendStatus()
  if (supervisorStatusRevision === requestedAtRevision) {
    supervisorStatus = { ...latestStatus }
    supervisorStatusRevision += 1
  }
  if (supervisorStatus.state === 'ready') return
  setRuntimeStatus(supervisorStatus)
  await new Promise<void>((resolve, reject) => {
    const finish = () => {
      clearTimeout(timeoutId)
      supervisorReadyWaiters.delete(finish)
      if (supervisorStatus.state === 'ready') resolve()
      else reject(new Error('Electron Backend did not become ready for runtime rebind'))
    }
    const timeoutId = setTimeout(finish, RUNTIME_REBIND_READY_TIMEOUT_MS)
    supervisorReadyWaiters.add(finish)
  })
}

function setRuntimeStatus(status: BackendStatus): void {
  runtimeStatus = { ...status }
  for (const listener of runtimeStatusListeners) listener({ ...runtimeStatus })
}

function logPlatformDiagnostic(event: string, details: Record<string, string | number | boolean>): void {
  console.info(event, details)
}

function normalizeApiBase(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

function runtimePort(apiBaseUrl: string): string {
  try {
    return new URL(apiBaseUrl).port
  } catch {
    return ''
  }
}
