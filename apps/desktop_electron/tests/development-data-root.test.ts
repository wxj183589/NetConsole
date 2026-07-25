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
    expect(resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'persistent',
      NETCONSOLE_DATA_ROOT: 'D:\\NetConsoleData',
    }, 'C:\\Temp'))
      .toMatchObject({ mode: 'persistent', persistent: true, dataRoot: 'D:\\NetConsoleData' })
  })

  it('rejects a persistent root located in a program installation tree', () => {
    expect(() => resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'persistent',
      NETCONSOLE_DATA_ROOT: 'D:\\Program Files\\NetConsole\\data',
      ProgramFiles: 'D:\\Program Files',
    }, 'C:\\Temp', 'win32')).toThrow('程序安装目录')
  })

  it('accepts and cleans only the exact isolated runtime layout', () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'netconsole-electron-test-'))
    const runtimeRoot = join(tempRoot, 'NetConsole-Codex-safe')
    const dataRoot = runtimeRoot
    const userDataRoot = join(runtimeRoot, 'runtime', 'electron', 'user-data')
    mkdirSync(dataRoot, { recursive: true })
    mkdirSync(userDataRoot, { recursive: true })
    try {
      const context = resolveDesktopStorageContext({
        NETCONSOLE_STORAGE_MODE: 'isolated_test',
        NETCONSOLE_RUNTIME_MODE: 'test',
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DATA_ROOT: dataRoot,
      }, tempRoot)
      expect(context).toMatchObject({ mode: 'isolated_test', persistent: false, dataRoot: runtimeRoot, userDataRoot })
      cleanupIsolatedDesktopRuntime(context.dataRoot, tempRoot)
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
      NETCONSOLE_RUNTIME_MODE: 'test',
      NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
    }, 'C:\\Temp')).toThrow('data root is missing')
  })
})
