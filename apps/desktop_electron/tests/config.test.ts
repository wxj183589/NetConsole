import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  DESKTOP_SAFE_BACKGROUND_COLOR,
  isDevelopmentMenuEnabled,
  loadDesktopConfig,
  resolveDesktopBackgroundColor,
} from '../src/main/config'

describe('desktop config', () => {
  it('uses a safe light initial background and fixed resolved-theme colors', () => {
    expect(DESKTOP_SAFE_BACKGROUND_COLOR).toBe('#f4f6f8')
    expect(resolveDesktopBackgroundColor('light')).toBe('#f4f6f8')
    expect(resolveDesktopBackgroundColor('dark')).toBe('#0f141c')
    const mainSource = readFileSync(fileURLToPath(new URL('../src/main/index.ts', import.meta.url)), 'utf8')
    expect(mainSource).toContain('backgroundColor: DESKTOP_SAFE_BACKGROUND_COLOR')
  })

  it('uses only an exact loopback Vite origin and an absolute developer Python', () => {
    const config = loadDesktopConfig({
      isPackaged: false,
      appPath: 'C:\\repo\\apps\\desktop_electron',
      resourcesPath: 'C:\\resources',
      platform: 'win32',
      env: {
        NETCONSOLE_PROJECT_ROOT: 'C:\\repo',
        NETCONSOLE_PYTHON: 'C:\\repo\\.venv\\Scripts\\python.exe',
        NETCONSOLE_WEB_DEV_URL: 'http://127.0.0.1:5173',
        NETCONSOLE_BACKEND_TIMEOUT_MS: '12000',
        LOCALAPPDATA: 'C:\\Users\\tester\\AppData\\Local',
      },
      fileExists: () => true,
    })

    expect(config).toMatchObject({
      projectRoot: 'C:\\repo',
      dataRoot: 'C:\\Users\\tester\\AppData\\Local\\NetConsole\\Development',
      runtimeMode: 'desktop-development',
      backendExecutable: 'C:\\repo\\.venv\\Scripts\\python.exe',
      backendArgumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      backendPythonPath: 'C:\\repo\\src',
      devServerUrl: 'http://127.0.0.1:5173',
      rendererOrigin: 'http://127.0.0.1:5173',
      startupTimeoutMs: 12000,
    })
  })

  it.each([
    'https://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:5173/path',
    'http://example.com:5173',
  ])('rejects an unsafe development URL: %s', (url) => {
    expect(() => loadDesktopConfig({
      isPackaged: false,
      appPath: 'C:\\repo\\apps\\desktop_electron',
      resourcesPath: 'C:\\resources',
      platform: 'win32',
      env: {
        NETCONSOLE_PYTHON: 'C:\\repo\\python.exe',
        NETCONSOLE_WEB_DEV_URL: url,
      },
      fileExists: () => true,
    })).toThrow('http://127.0.0.1')
  })

  it('does not accept a developer override for a packaged backend', () => {
    const config = loadDesktopConfig({
      isPackaged: true,
      appPath: 'C:\\installed\\resources\\app.asar',
      resourcesPath: 'C:\\installed\\resources',
      platform: 'win32',
      env: {
        NETCONSOLE_PYTHON: 'C:\\untrusted\\python.exe',
        LOCALAPPDATA: 'C:\\Users\\tester\\AppData\\Local',
      },
      fileExists: () => true,
    })

    expect(config.backendExecutable).toBe('C:\\installed\\resources\\backend\\NetConsoleBackend.exe')
    expect(config.backendArgumentsPrefix).toEqual(['--electron-backend'])
    expect(config.dataRoot).toBe('C:\\Users\\tester\\AppData\\Local\\NetConsole')
    expect(config).not.toHaveProperty('backendPythonPath')
  })

  it('rejects a desktop data root inside the project', () => {
    expect(() => loadDesktopConfig({
      isPackaged: false,
      appPath: 'C:\\repo\\apps\\desktop_electron',
      resourcesPath: 'C:\\resources',
      platform: 'win32',
      env: {
        NETCONSOLE_PYTHON: 'C:\\repo\\.venv\\Scripts\\python.exe',
        NETCONSOLE_DATA_ROOT: 'C:\\repo\\.local',
      },
      fileExists: () => true,
    })).toThrow('must not be inside')
  })

  it('shows the default menu only for an explicitly enabled development server', () => {
    expect(isDevelopmentMenuEnabled(undefined, {
      NETCONSOLE_ELECTRON_DEV_MENU: '1',
    })).toBe(false)
    expect(isDevelopmentMenuEnabled('http://127.0.0.1:5173', {})).toBe(false)
    expect(isDevelopmentMenuEnabled('http://127.0.0.1:5173', {
      NETCONSOLE_ELECTRON_DEV_MENU: '1',
    })).toBe(true)
  })
})
