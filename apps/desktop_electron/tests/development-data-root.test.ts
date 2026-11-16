import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  cleanupIsolatedDesktopRuntime,
  resolveDesktopStorageContext,
  WINDOWS_TEST_DATA_ROOT,
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

  it('accepts a persistent root on C: while keeping the installation-tree guard', () => {
    expect(resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'persistent',
      NETCONSOLE_DATA_ROOT: 'C:\\ProgramData\\NetConsole\\Data',
    }, 'D:\\Temp', 'win32')).toMatchObject({
      mode: 'persistent',
      persistent: true,
      dataRoot: 'C:\\ProgramData\\NetConsole\\Data',
    })
  })

  it('rejects a custom portable root inside the executable directory', () => {
    expect(() => resolveDesktopStorageContext({
      NETCONSOLE_STORAGE_MODE: 'persistent',
      NETCONSOLE_DATA_ROOT: 'D:\\Portable\\custom-data',
    }, 'C:\\Temp', 'win32', {
      portableMode: true,
      portableAppRoot: 'D:\\Portable',
    })).toThrow('程序目录')
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

  it('rejects sibling-prefix paths and redirected isolated roots', () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'netconsole-electron-boundary-'))
    const root = join(WINDOWS_TEST_DATA_ROOT, 'boundary-test')
    mkdirSync(root, { recursive: true })
    try {
      expect(() => resolveDesktopStorageContext({
        NETCONSOLE_STORAGE_MODE: 'isolated_test',
        NETCONSOLE_RUNTIME_MODE: 'test',
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DATA_ROOT: `${WINDOWS_TEST_DATA_ROOT}-sibling`,
      }, tempRoot)).toThrow('unexpected isolated desktop runtime')

      const outside = join(tempRoot, 'outside')
      const redirected = join(root, 'redirected')
      mkdirSync(outside, { recursive: true })
      try {
        symlinkSync(outside, redirected, 'junction')
      } catch {
        return
      }
      expect(() => resolveDesktopStorageContext({
        NETCONSOLE_STORAGE_MODE: 'isolated_test',
        NETCONSOLE_RUNTIME_MODE: 'test',
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DATA_ROOT: redirected,
      }, tempRoot)).toThrow(/redirected outside|symbolic-link/)
    } finally {
      rmSync(root, { recursive: true, force: true })
      rmSync(tempRoot, { recursive: true, force: true })
    }
  })
})
