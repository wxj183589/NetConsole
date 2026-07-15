import type { PlatformAdapter } from './types'

const DESKTOP_ONLY_MESSAGE = '当前能力仅在 NetConsole Electron Desktop 中可用'

export function createBrowserAdapter(apiBaseUrl = ''): PlatformAdapter {
  return {
    hostType: 'browser',
    getAppInfo: async () => ({ version: '', platform: 'browser', isPackaged: false }),
    getBackendStatus: async () => ({ state: 'stopped' }),
    getRuntimeConfig: async () => ({ apiBaseUrl: normalizeBaseUrl(apiBaseUrl), apiToken: '' }),
    selectFile: async () => ({ cancelled: true, paths: [] }),
    selectDirectory: async () => ({ cancelled: true }),
    chooseSavePath: async () => ({ cancelled: true }),
    openPath: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    showItemInFolder: async () => ({ success: false, error: DESKTOP_ONLY_MESSAGE }),
    onBackendStatusChanged: () => () => undefined,
    reportRendererReady: () => undefined,
  }
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '')
}
