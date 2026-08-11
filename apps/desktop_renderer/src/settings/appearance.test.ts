// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { applySafeSystemAppearance, initializeSystemAppearance } from './appearance'
import type { SystemSettingsSnapshot } from '../types/systemSettings'

const snapshot = (): SystemSettingsSnapshot => ({
  version: '1',
  values: {
    theme: 'dark',
    language: 'zh_CN',
    theme_color: '#2563EB',
    iperf_path: '',
    fping_path: '',
    ipop_path: '',
    terminal_type: 'putty',
    terminal_paths: { putty: '', securecrt: '', xshell: '' },
    securecrt_sessions_root: '',
    ssh_port: 22,
    telnet_port: 23,
    crt_encoding: 'UTF-8',
  },
  defaults: {} as SystemSettingsSnapshot['defaults'],
  current_site_name: 'demo',
  current_site_path: '',
  language_status: 'BLOCKED_ON_GLOBAL_I18N',
})

afterEach(() => {
  vi.restoreAllMocks()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('style')
  Reflect.deleteProperty(window, 'netconsoleDesktop')
})

describe('system appearance bootstrap', () => {
  it('applies the safe default and saved appearance before Vue mounts', () => {
    const mainSource = readFileSync(resolve(process.cwd(), 'src', 'main.ts'), 'utf8')
    expect(mainSource).toContain('if (!window.netconsoleDesktop) applySafeSystemAppearance()')
    expect(mainSource.indexOf('applySafeSystemAppearance()')).toBeLessThan(
      mainSource.indexOf('await initializePlatformRuntime()'),
    )
    expect(mainSource.indexOf('await initializeSystemAppearance()')).toBeLessThan(
      mainSource.indexOf('createApp(App)'),
    )
  })

  it('applies the shared settings source for Browser and Electron renderers', async () => {
    const load = vi.fn().mockResolvedValue(snapshot())

    await expect(initializeSystemAppearance(load)).resolves.toBe(true)
    expect(load).toHaveBeenCalledOnce()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.documentElement.style.getPropertyValue('--nc-primary')).toBe('#2563EB')
  })

  it('keeps the safe default appearance when settings are unavailable', async () => {
    document.documentElement.dataset.theme = 'dark'
    document.documentElement.style.setProperty('--nc-primary', '#16A34A')

    await expect(initializeSystemAppearance(() => Promise.reject(new Error('offline')))).resolves.toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.documentElement.style.getPropertyValue('--nc-primary')).toBe('#0078D4')
  })

  it('does not report the invisible safe default as the persisted Electron theme', () => {
    const reportRendererReady = vi.fn()
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { reportRendererReady },
    })

    applySafeSystemAppearance()

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(reportRendererReady).not.toHaveBeenCalled()
  })
})
