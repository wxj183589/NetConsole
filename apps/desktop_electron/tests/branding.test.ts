import { existsSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  NETCONSOLE_TASK_WINDOW_TITLE,
  NETCONSOLE_WINDOW_TITLE,
  resolveDesktopIconPath,
} from '../src/main/branding'

const appRoot = resolve(import.meta.dirname, '..')
const repoRoot = resolve(appRoot, '..', '..')

describe('desktop branding resources', () => {
  it('uses the requested window titles', () => {
    expect(NETCONSOLE_WINDOW_TITLE).toBe('NetConsole v1.4.2 by wxj')
    expect(NETCONSOLE_TASK_WINDOW_TITLE).toBe('NetConsole v1.4.2 by wxj - 任务中心')
  })

  it('resolves development and packaged icon paths without absolute project literals', () => {
    const developmentIcon = resolveDesktopIconPath({
      isPackaged: false,
      appPath: appRoot,
      resourcesPath: resolve(appRoot, 'unused'),
    })
    const packagedIcon = resolveDesktopIconPath({
      isPackaged: true,
      appPath: resolve(appRoot, 'unused'),
      resourcesPath: resolve(appRoot, 'dist', 'resources'),
    })

    expect(developmentIcon).toBe(resolve(repoRoot, 'resources', 'branding', 'netconsole.ico'))
    expect(packagedIcon).toBe(resolve(appRoot, 'dist', 'resources', 'branding', 'netconsole.ico'))
    expect(developmentIcon).not.toContain('C:\\Users\\')
    expect(existsSync(developmentIcon)).toBe(true)
    expect(statSync(developmentIcon).size).toBeGreaterThan(0)
    expect(statSync(resolve(repoRoot, 'resources', 'branding', 'netconsole.png')).size).toBeGreaterThan(0)
  })
})
