import { existsSync } from 'node:fs'
import { isAbsolute, resolve } from 'node:path'

export interface DesktopConfig {
  projectRoot: string
  backendExecutable: string
  backendArgumentsPrefix: string[]
  devServerUrl?: string
  rendererOrigin?: string
  startupTimeoutMs: number
}

export interface DesktopConfigInput {
  isPackaged: boolean
  appPath: string
  resourcesPath: string
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

  return {
    projectRoot,
    backendExecutable,
    backendArgumentsPrefix: input.isPackaged ? [] : ['-m', 'netconsole.backend.electron_runtime'],
    ...(devServerUrl ? { devServerUrl, rendererOrigin: new URL(devServerUrl).origin } : {}),
    startupTimeoutMs: parseTimeout(env.NETCONSOLE_BACKEND_TIMEOUT_MS),
  }
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
