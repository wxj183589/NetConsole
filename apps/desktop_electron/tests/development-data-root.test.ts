import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  cleanupIsolatedDesktopRuntime,
  resolveDesktopStorageContext,
} from '../src/main/development-data-root'

describe('Electron desktop storage context', () => {
  it('uses persistent storage without temporary markers', () => {
    expect(resolveDesktopStorageContext({ NETCONSOLE_STORAGE_MODE: 'persistent' }, 'C:\\Temp'))
      .toEqual({ mode: 'persistent', persistent: true })
  })

  it('accepts and cleans only the exact isolated runtime layout', () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'netconsole-electron-test-'))
    const runtimeRoot = join(tempRoot, 'NetConsole-Codex-safe')
    const dataRoot = join(runtimeRoot, 'data')
    const userDataRoot = join(runtimeRoot, 'electron-user-data')
    mkdirSync(dataRoot, { recursive: true })
    mkdirSync(userDataRoot, { recursive: true })
    try {
      const context = resolveDesktopStorageContext({
        NETCONSOLE_STORAGE_MODE: 'isolated_test',
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DATA_ROOT: dataRoot,
        NETCONSOLE_DEV_TEMP_USER_DATA_ROOT: userDataRoot,
      }, tempRoot)
      expect(context).toMatchObject({ mode: 'isolated_test', persistent: false, temporaryRoot: runtimeRoot, userDataRoot })
      cleanupIsolatedDesktopRuntime(context.temporaryRoot!, tempRoot)
      expect(existsSync(runtimeRoot)).toBe(false)
    } finally {
      rmSync(tempRoot, { recursive: true, force: true })
    }
  })

  it('rejects persistent markers and incomplete isolated paths', () => {
    expect(() => resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'persistent',
      NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
    }, 'C:\\Temp')).toThrow('must not use temporary')
    expect(() => resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'isolated_test',
      NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
      NETCONSOLE_DATA_ROOT: 'C:\\Temp\\NetConsole-Codex-safe\\data',
    }, 'C:\\Temp')).toThrow('paths are missing')
  })
})
