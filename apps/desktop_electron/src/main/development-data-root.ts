import { mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, isAbsolute, resolve, sep } from 'node:path'

export type DesktopStorageMode = 'persistent' | 'isolated_test'

export interface DesktopStorageContext {
  mode: DesktopStorageMode
  persistent: boolean
  dataRoot: string
  userDataRoot: string
  sessionDataRoot: string
  cacheRoot: string
  logsRoot: string
  crashDumpsRoot: string
  tempRoot: string
}

export const WINDOWS_TEST_DATA_ROOT = 'D:\\NetConsoleTestData'

export function resolveDesktopStorageContext(
  environment: NodeJS.ProcessEnv = process.env,
  systemTempRoot = tmpdir(),
  platform: NodeJS.Platform = process.platform,
): DesktopStorageContext {
  const requestedMode = environment.NETCONSOLE_STORAGE_MODE?.trim() || 'persistent'
  const configuredRoot = environment.NETCONSOLE_DATA_ROOT?.trim()
  if (requestedMode === 'persistent') {
    if (environment.NETCONSOLE_DEV_TEMP_DATA_ROOT === '1' || environment.NETCONSOLE_DEV_TEMP_USER_DATA_ROOT) {
      throw new Error('Persistent desktop runtime must not use temporary storage markers')
    }
    if (!configuredRoot) {
      throw new Error('尚未配置 NetConsole 数据目录。请通过安装程序选择非系统盘的数据存放位置。')
    }
    const dataRoot = validatePersistentDataRoot(
      configuredRoot,
      environment,
      systemTempRoot,
      platform,
    )
    return buildContext('persistent', dataRoot)
  }
  if (
    requestedMode !== 'isolated_test'
    || environment.NETCONSOLE_DEV_TEMP_DATA_ROOT !== '1'
    || environment.NETCONSOLE_RUNTIME_MODE !== 'test'
  ) {
    throw new Error('Desktop storage mode is invalid')
  }
  if (!configuredRoot) throw new Error('Isolated desktop data root is missing')
  const dataRoot = validateIsolatedPath(configuredRoot, WINDOWS_TEST_DATA_ROOT)
  return buildContext('isolated_test', dataRoot)
}

export function ensureDesktopRuntimePaths(context: DesktopStorageContext): void {
  for (const path of [
    context.dataRoot,
    context.userDataRoot,
    context.sessionDataRoot,
    context.cacheRoot,
    context.logsRoot,
    context.crashDumpsRoot,
    context.tempRoot,
  ]) mkdirSync(path, { recursive: true })
}

export function cleanupIsolatedDesktopRuntime(value: string, testDataRoot = WINDOWS_TEST_DATA_ROOT): void {
  const target = validateIsolatedPath(value, testDataRoot)
  rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
}

function buildContext(mode: DesktopStorageMode, dataRoot: string): DesktopStorageContext {
  const runtimeRoot = resolve(dataRoot, 'runtime')
  const electronRoot = resolve(runtimeRoot, 'electron')
  return {
    mode,
    persistent: mode === 'persistent',
    dataRoot,
    userDataRoot: resolve(electronRoot, 'user-data'),
    sessionDataRoot: resolve(electronRoot, 'session-data'),
    cacheRoot: resolve(electronRoot, 'cache'),
    logsRoot: resolve(runtimeRoot, 'logs'),
    crashDumpsRoot: resolve(electronRoot, 'crash-dumps'),
    tempRoot: resolve(runtimeRoot, 'temp'),
  }
}

function validateIsolatedPath(value: string, testDataRoot: string): string {
  const target = resolve(value)
  const root = resolve(testDataRoot)
  if (target === root || !target.startsWith(`${root}${sep}`) || !basename(target)) {
    throw new Error('Refusing to use an unexpected isolated desktop runtime')
  }
  return target
}

function validatePersistentDataRoot(
  value: string,
  environment: NodeJS.ProcessEnv,
  systemTempRoot: string,
  platform: NodeJS.Platform,
): string {
  if (!value || !isAbsolute(value)) throw new Error('NETCONSOLE_DATA_ROOT must be an absolute path')
  const target = resolve(value)
  const temporary = resolve(systemTempRoot)
  if (target === temporary || target.startsWith(`${temporary}${sep}`)) {
    throw new Error('NetConsole data root must not use the system temporary directory')
  }
  if (platform === 'win32') {
    const systemDrive = (environment.SystemDrive?.trim() || 'C:').toLowerCase()
    if (target.slice(0, 2).toLowerCase() === systemDrive) {
      throw new Error(`NetConsole 数据根不得位于系统盘：${target}`)
    }
    const forbiddenRoots: Array<[string, string | undefined]> = [
      ['AppData', environment.LOCALAPPDATA],
      ['AppData', environment.APPDATA],
      ['用户 Profile', environment.USERPROFILE],
      ['程序安装目录', environment.ProgramFiles],
      ['程序安装目录', environment['ProgramFiles(x86)']],
      ['程序安装目录', environment.ProgramW6432],
      ['Windows 目录', environment.SystemRoot],
      ['Windows 目录', environment.WINDIR],
    ]
    for (const [label, rawRoot] of forbiddenRoots) {
      if (!rawRoot || !isAbsolute(rawRoot)) continue
      const root = resolve(rawRoot)
      if (target === root || target.startsWith(`${root}${sep}`)) {
        throw new Error(`NetConsole 数据根不得位于${label}：${target}`)
      }
    }
  }
  return target
}
