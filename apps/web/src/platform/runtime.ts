import { createBrowserAdapter } from './browser-adapter'
import { createElectronAdapter } from './electron-adapter'
import type { ActiveRuntimeConfig, PlatformAdapter } from './types'

const browserApiBase = import.meta.env.VITE_API_BASE || ''

let adapter: PlatformAdapter = createBrowserAdapter(browserApiBase)
let config: ActiveRuntimeConfig = {
  hostType: 'browser',
  apiBaseUrl: browserApiBase.trim().replace(/\/+$/, ''),
  apiToken: '',
}

export async function initializePlatformRuntime(): Promise<ActiveRuntimeConfig> {
  adapter = window.netconsoleDesktop
    ? createElectronAdapter(window.netconsoleDesktop)
    : createBrowserAdapter(browserApiBase)
  const runtime = await adapter.getRuntimeConfig()
  config = { ...runtime, hostType: adapter.hostType }
  return { ...config }
}

export function getPlatformAdapter(): PlatformAdapter {
  return adapter
}

export function getRuntimeConfig(): ActiveRuntimeConfig {
  return { ...config }
}

export function resolveApiUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('API path must start with /')
  return config.apiBaseUrl ? new URL(path, `${config.apiBaseUrl}/`).toString() : path
}

export function resolveWebSocketUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('WebSocket path must start with /')
  const locationOrigin = window.location.origin
    || `${window.location.protocol}//${window.location.host}`
  const base = config.apiBaseUrl || locationOrigin
  const url = new URL(path, `${base.replace(/\/+$/, '')}/`)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export function resolveFrontendAssetUrl(path: string): string {
  if (!path.startsWith('/')) throw new Error('asset path must start with /')
  if (config.hostType === 'electron' && config.apiBaseUrl) {
    return new URL(path, `${config.apiBaseUrl}/`).toString()
  }
  return path
}

export function resetPlatformRuntimeForTests(apiBaseUrl = ''): void {
  adapter = createBrowserAdapter(apiBaseUrl)
  config = { hostType: 'browser', apiBaseUrl, apiToken: '' }
}
