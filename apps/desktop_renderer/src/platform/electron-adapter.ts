import type {
  BackendStatus,
  DesktopRuntimeConfig,
  NetConsoleDesktopBridge,
} from '../../../desktop_electron/src/shared/bridge'

import type { PlatformAdapter } from './types'
import { requestTaskCenterOpen } from '../task-center/events'

const TOKEN_RE = /^[A-Za-z0-9_-]{32,256}$/

export function createElectronAdapter(bridge: NetConsoleDesktopBridge): PlatformAdapter {
  return {
    hostType: 'electron',
    getAppInfo: () => bridge.getAppInfo(),
    getBackendStatus: async () => validateBackendStatus(await bridge.getBackendStatus()),
    getRuntimeConfig: async () => validateRuntimeConfig(await bridge.getRuntimeConfig()),
    selectFile: (options) => bridge.selectFile(options),
    selectDirectory: () => bridge.selectDirectory(),
    selectSettingsTool: (toolId) => bridge.selectSettingsTool(toolId),
    selectSettingsDirectory: (directoryId) => bridge.selectSettingsDirectory(directoryId),
    selectSettingsColor: () => bridge.selectSettingsColor(),
    executeSettingsAction: (actionId) => bridge.executeSettingsAction(actionId),
    selectDataRootDirectory: () => bridge.selectDataRootDirectory(),
    selectSitePackage: () => bridge.selectSitePackage(),
    selectSiteExportDestination: (suggestedName) => bridge.selectSiteExportDestination(suggestedName),
    restartBackend: (request) => bridge.restartBackend(request),
    restartApplication: () => bridge.restartApplication(),
    refreshSiteContext: async () => { await bridge.refreshSiteContext?.() },
    chooseSavePath: (options) => bridge.chooseSavePath(options),
    downloadBackendResource: (request) => bridge.downloadBackendResource(request),
    openTaskWindow: async (context) => {
      requestTaskCenterOpen(context)
      return { success: true }
    },
    showTaskNotification: (payload) => bridge.showTaskNotification(payload),
    setTaskTrayStatus: (status) => bridge.setTaskTrayStatus(status),
    onTaskCenterOpenRequested: (listener) => bridge.onTaskCenterOpenRequested?.(listener) ?? (() => undefined),
    openMeshAnalysisSessionLocation: (sessionId) => bridge.openMeshAnalysisSessionLocation?.(sessionId)
      ?? Promise.resolve({ success: false, error: 'Electron MESH 本地目录组件未加载，请重启 NetConsole' }),
    openPath: (capabilityId) => bridge.openPath(capabilityId),
    showItemInFolder: (capabilityId) => bridge.showItemInFolder(capabilityId),
    openExternalUrl: (url) => bridge.openExternalUrl(url),
    writeClipboardText: (text) => bridge.writeClipboardText?.(text)
      ?? Promise.resolve({ success: false, error: 'Electron 剪贴板组件未加载，请重启 NetConsole' }),
    onBackendStatusChanged: (listener) => bridge.onBackendStatusChanged((status) => {
      listener(validateBackendStatus(status))
    }),
    onTraySiteSwitchRequested: (listener) => bridge.onTraySiteSwitchRequested?.((request) => {
      listener(request.siteId)
    }) ?? (() => undefined),
    reportSiteSwitchState: (switching) => bridge.reportSiteSwitchState?.(switching),
    reportRendererReady: (healthOk, phase = 'interactive', surface) => bridge.reportRendererReady({
      healthOk,
      phase,
      ...(surface ? { surface } : {}),
    }),
  }
}

export function validateRuntimeConfig(value: DesktopRuntimeConfig): DesktopRuntimeConfig {
  let url: URL
  try {
    url = new URL(value.apiBaseUrl)
  } catch {
    throw new Error('Electron 返回了无效的本地 API 地址')
  }
  if (
    url.protocol !== 'http:'
    || url.hostname !== '127.0.0.1'
    || !url.port
    || url.username
    || url.password
    || url.pathname !== '/'
    || url.search
    || url.hash
  ) {
    throw new Error('Electron 本地 API 必须使用动态 127.0.0.1 回环端口')
  }
  if (!TOKEN_RE.test(value.apiToken)) throw new Error('Electron 返回了无效的临时 API 令牌')
  return { apiBaseUrl: url.origin, apiToken: value.apiToken }
}

function validateBackendStatus(value: BackendStatus): BackendStatus {
  if (!['starting', 'ready', 'stopped', 'failed'].includes(value.state)) {
    throw new Error('Electron 返回了无效的后端状态')
  }
  return {
    state: value.state,
    ...(typeof value.baseUrl === 'string' ? { baseUrl: value.baseUrl } : {}),
    ...(typeof value.error === 'string' ? { error: value.error } : {}),
  }
}
