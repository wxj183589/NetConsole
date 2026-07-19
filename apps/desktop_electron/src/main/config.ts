import { existsSync } from 'node:fs'
import { isAbsolute, relative, resolve } from 'node:path'

import type { DesktopResolvedTheme } from '../shared/bridge'

export const DESKTOP_SAFE_BACKGROUND_COLOR = '#f4f6f8'

const DESKTOP_THEME_BACKGROUND = Object.freeze({
  light: DESKTOP_SAFE_BACKGROUND_COLOR,
  dark: '#0f141c',
} satisfies Record<DesktopResolvedTheme, string>)

export function resolveDesktopBackgroundColor(theme: DesktopResolvedTheme): string {
  return DESKTOP_THEME_BACKGROUND[theme]
}

export interface DesktopConfig {
  projectRoot: string
  dataRoot: string
  activeSiteId: string
  runtimeMode: 'desktop-development' | 'desktop-packaged'
  backendExecutable: string
  backendArgumentsPrefix: string[]
  backendPythonPath?: string
  devServerUrl?: string
  rendererOrigin?: string
  startupTimeoutMs: number
}

export interface DesktopConfigInput {
  isPackaged: boolean
  appPath: string
  resourcesPath: string
  userDataPath?: string
  bootstrapDataRoot?: string
  bootstrapActiveSiteId?: string
  env?: NodeJS.ProcessEnv
  platform?: NodeJS.Platform
  fileExists?: (path: string) => boolean
}

export function loadDesktopConfig(input: DesktopConfigInput): DesktopConfig {
  const env = input.env ?? process.env
  const platform = input.platform ?? process.platform
  const fileExists = input.fileExists ?? existsSync
  const devServerUrl = input.isPackaged ? undefined : optionalLoopbackDevUrl(env.NETCONSOLE_WEB_DEV_URL)
  const projectRoot = input.isPackaged
    ? input.resourcesPath
    : resolveDeveloperPath(env.NETCONSOLE_PROJECT_ROOT, resolve(input.appPath, '..', '..'), 'project root')
  const backendExecutable = input.isPackaged
    ? resolve(input.resourcesPath, 'backend', platform === 'win32' ? 'NetConsoleBackend.exe' : 'netconsole-backend')
    : resolveDeveloperPython(env.NETCONSOLE_PYTHON, projectRoot, platform)

  if (!fileExists(backendExecutable)) {
    throw new Error(
      input.isPackaged
        ? 'Electron 安装包缺少受管 Python 后端，请重新安装完整版本。'
        : `未找到项目 Python 运行时：${backendExecutable}`,
    )
  }
  const dataRoot = resolveDesktopDataRoot(input, projectRoot, env, platform)

  return {
    projectRoot,
    dataRoot,
    activeSiteId: normalizeActiveSiteId(input.bootstrapActiveSiteId),
    runtimeMode: input.isPackaged ? 'desktop-packaged' : 'desktop-development',
    backendExecutable,
    backendArgumentsPrefix: input.isPackaged
      ? ['--electron-backend']
      : ['-m', 'netconsole.backend.electron_runtime'],
    ...(!input.isPackaged ? { backendPythonPath: resolve(projectRoot, 'src') } : {}),
    ...(devServerUrl ? { devServerUrl, rendererOrigin: new URL(devServerUrl).origin } : {}),
    startupTimeoutMs: parseTimeout(env.NETCONSOLE_BACKEND_TIMEOUT_MS),
  }
}

function resolveDesktopDataRoot(
  input: DesktopConfigInput,
  projectRoot: string,
  env: NodeJS.ProcessEnv,
  platform: NodeJS.Platform,
): string {
  const override = env.NETCONSOLE_DATA_ROOT?.trim() || input.bootstrapDataRoot?.trim()
  let candidate: string
  if (override) {
    candidate = resolveDeveloperPath(override, '', 'NETCONSOLE_DATA_ROOT')
  } else if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA?.trim()
    if (!localAppData) throw new Error('LOCALAPPDATA is required to resolve the desktop data root')
    candidate = resolve(localAppData, 'NetConsole', ...(input.isPackaged ? [] : ['Development']))
  } else {
    if (!input.userDataPath) throw new Error('userDataPath is required to resolve the desktop data root')
    candidate = input.isPackaged
      ? resolve(input.userDataPath)
      : resolve(input.userDataPath, 'Development')
  }
  const fromProject = relative(projectRoot, candidate)
  if (!fromProject || (!fromProject.startsWith('..') && !isAbsolute(fromProject))) {
    throw new Error('Electron data root must not be inside the project or installation directory')
  }
  return candidate
}

function normalizeActiveSiteId(value: string | undefined): string {
  const candidate = value?.trim() || 'demo'
  if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(candidate)) return 'demo'
  return candidate
}

export function isDevelopmentMenuEnabled(
  devServerUrl: string | undefined,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  return Boolean(devServerUrl) && env.NETCONSOLE_ELECTRON_DEV_MENU === '1'
}

function resolveDeveloperPython(
  override: string | undefined,
  projectRoot: string,
  platform: NodeJS.Platform,
): string {
  if (override) return resolveDeveloperPath(override, '', 'Python executable')
  return platform === 'win32'
    ? resolve(projectRoot, '.venv', 'Scripts', 'python.exe')
    : resolve(projectRoot, '.venv', 'bin', 'python')
}

function resolveDeveloperPath(value: string | undefined, fallback: string, label: string): string {
  const candidate = value?.trim() || fallback
  if (!candidate || !isAbsolute(candidate)) throw new Error(`${label} must be an absolute path`)
  if (/\u0000/.test(candidate)) throw new Error(`${label} is invalid`)
  return resolve(candidate)
}

function optionalLoopbackDevUrl(value: string | undefined): string | undefined {
  const candidate = value?.trim()
  if (!candidate) return undefined
  let parsed: URL
  try {
    parsed = new URL(candidate)
  } catch {
    throw new Error('NETCONSOLE_WEB_DEV_URL must be a valid URL')
  }
  if (
    parsed.protocol !== 'http:'
    || parsed.hostname !== '127.0.0.1'
    || !parsed.port
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash
  ) {
    throw new Error('NETCONSOLE_WEB_DEV_URL must be an http://127.0.0.1:<port> origin')
  }
  return parsed.origin
}

function parseTimeout(value: string | undefined): number {
  if (!value) return 15_000
  const timeout = Number(value)
  if (!Number.isInteger(timeout) || timeout < 1_000 || timeout > 60_000) {
    throw new Error('NETCONSOLE_BACKEND_TIMEOUT_MS must be between 1000 and 60000')
  }
  return timeout
}
