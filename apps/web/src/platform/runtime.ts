import { createBrowserAdapter } from './browser-adapter'
import { createElectronAdapter } from './electron-adapter'
import type { ActiveRuntimeConfig, PlatformAdapter } from './types'
import type {
  BackendDownloadRequest,
  BackendDownloadResult,
} from '../../../desktop_electron/src/shared/bridge'

const browserApiBase = import.meta.env.VITE_API_BASE || ''
const browserDevelopmentToken = import.meta.env.DEV
  ? import.meta.env.VITE_DEV_SESSION_TOKEN || ''
  : ''

let adapter: PlatformAdapter = createBrowserAdapter(browserApiBase, browserDevelopmentToken)
let config: ActiveRuntimeConfig = {
  hostType: 'browser',
  apiBaseUrl: browserApiBase.trim().replace(/\/+$/, ''),
  apiToken: '',
}
let initializationState: 'uninitialized' | 'initializing' | 'ready' | 'failed' = 'uninitialized'

export async function initializePlatformRuntime(): Promise<ActiveRuntimeConfig> {
  initializationState = 'initializing'
  try {
    adapter = window.netconsoleDesktop
      ? createElectronAdapter(window.netconsoleDesktop)
      : createBrowserAdapter(browserApiBase, browserDevelopmentToken)
    const runtime = await adapter.getRuntimeConfig()
    config = {
      ...runtime,
      apiBaseUrl: normalizeApiBase(runtime.apiBaseUrl),
      hostType: adapter.hostType,
    }
    initializationState = 'ready'
    return { ...config }
  } catch (cause) {
    initializationState = 'failed'
    throw cause
  }
}

export function getPlatformAdapter(): PlatformAdapter {
  return adapter
}

export function getRuntimeConfig(): ActiveRuntimeConfig {
  return { ...config }
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
  adapter = createBrowserAdapter(apiBaseUrl)
  config = { hostType: 'browser', apiBaseUrl: normalizeApiBase(apiBaseUrl), apiToken: '' }
  initializationState = initialized ? 'ready' : 'uninitialized'
}

function assertElectronRuntimeReady(): void {
  if (initializationState === 'ready') return
  if (typeof window !== 'undefined' && window.netconsoleDesktop) {
    throw new Error('Electron 运行时尚未就绪，拒绝回退到相对 API 地址')
  }
}

function normalizeApiBase(value: string): string {
  return value.trim().replace(/\/+$/, '')
}
