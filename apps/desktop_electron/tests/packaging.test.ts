import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const appRoot = resolve(import.meta.dirname, '..')

describe('Electron-only packaging', () => {
  it('packages the managed backend and preserves user data on uninstall', () => {
    const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))

    expect(packageJson.scripts.package).toContain('electron-builder')
    expect(packageJson.scripts['smoke:package']).toContain('package-smoke.mjs')
    expect(packageJson.build.extraResources).toContainEqual({
      from: 'dist/package-resources/backend',
      to: 'backend',
    })
    expect(packageJson.build.nsis.deleteAppDataOnUninstall).toBe(false)
    expect(packageJson.build.win.target[0]).toEqual({ target: 'nsis', arch: ['x64'] })
  })

  it('builds the backend without a system Python dependency', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package.mjs'), 'utf8')

    expect(script).toContain('scripts.build.build_release')
    expect(script).toContain('NetConsoleBackend.exe')
    expect(script).toContain("'.venv', 'Scripts', 'python.exe'")
  })

  it('scans the packaged app for forbidden Qt runtime files', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8').toLowerCase()

    for (const marker of ['pyside6', 'shiboken6', 'qfluentwidgets', 'qt6core', 'qwindows.dll']) {
      expect(script).toContain(marker)
    }
    expect(script).toContain('netconsole_electron_smoke_test'.toLowerCase())
  })
})
