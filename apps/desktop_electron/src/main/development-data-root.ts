import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, resolve, sep } from 'node:path'

export type DesktopStorageMode = 'persistent' | 'isolated_test'

export interface DesktopStorageContext {
  mode: DesktopStorageMode
  persistent: boolean
  temporaryRoot?: string
  userDataRoot?: string
}

const ISOLATED_PREFIX = 'NetConsole-Codex-'

export function resolveDesktopStorageContext(
  environment: NodeJS.ProcessEnv = process.env,
  systemTempRoot = tmpdir(),
): DesktopStorageContext {
  const requestedMode = environment.NETCONSOLE_STORAGE_MODE?.trim() || 'persistent'
  if (requestedMode === 'persistent') {
    if (environment.NETCONSOLE_DEV_TEMP_DATA_ROOT === '1' || environment.NETCONSOLE_DEV_TEMP_USER_DATA_ROOT) {
      throw new Error('Persistent desktop runtime must not use temporary storage markers')
    }
    return { mode: 'persistent', persistent: true }
  }
  if (requestedMode !== 'isolated_test' || environment.NETCONSOLE_DEV_TEMP_DATA_ROOT !== '1') {
    throw new Error('Desktop storage mode is invalid')
  }
  const dataRoot = environment.NETCONSOLE_DATA_ROOT?.trim()
  const userDataRoot = environment.NETCONSOLE_DEV_TEMP_USER_DATA_ROOT?.trim()
  if (!dataRoot || !userDataRoot) throw new Error('Isolated desktop runtime paths are missing')
  const temporaryRoot = validateIsolatedPath(dirname(resolve(dataRoot)), systemTempRoot)
  if (resolve(dataRoot) !== resolve(temporaryRoot, 'data')) throw new Error('Isolated data root has an invalid layout')
  if (resolve(userDataRoot) !== resolve(temporaryRoot, 'electron-user-data')) {
    throw new Error('Isolated Electron userData has an invalid layout')
  }
  return {
    mode: 'isolated_test',
    persistent: false,
    temporaryRoot,
    userDataRoot: resolve(userDataRoot),
  }
}

export function cleanupIsolatedDesktopRuntime(value: string, systemTempRoot = tmpdir()): void {
  const target = validateIsolatedPath(value, systemTempRoot)
  rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
}

function validateIsolatedPath(value: string, systemTempRoot: string): string {
  const target = resolve(value)
  const tempRoot = resolve(systemTempRoot)
  if (!target.startsWith(`${tempRoot}${sep}`) || !basename(target).startsWith(ISOLATED_PREFIX)) {
    throw new Error('Refusing to use an unexpected isolated desktop runtime')
  }
  return target
}
