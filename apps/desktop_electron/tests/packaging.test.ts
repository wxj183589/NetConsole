import { cpSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

import { describe, expect, it } from 'vitest'

const appRoot = resolve(import.meta.dirname, '..')

describe('Electron-only packaging', () => {
  it('packages the managed backend and preserves user data on uninstall', () => {
    const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))

    expect(packageJson.scripts.package).toContain('electron-builder')
    expect(packageJson.scripts['smoke:package']).toContain('package-smoke.mjs')
    expect(packageJson.build.productName).toBe('NetConsole v1.4.2 by wxj')
    expect(packageJson.build.win.executableName).toBe('NetConsole')
    expect(packageJson.build.electronDist).toBe('node_modules/electron/dist')
    expect(packageJson.build.extraResources).toContainEqual({
      from: 'dist/package-resources/backend',
      to: 'backend',
    })
    expect(packageJson.build.extraResources).toContainEqual({
      from: '../../resources/branding',
      to: 'branding',
      filter: ['netconsole.ico', 'netconsole.png'],
    })
    expect(packageJson.build.win.icon).toBe('../../resources/branding/netconsole.ico')
    expect(packageJson.build.nsis.installerIcon).toBe('../../resources/branding/netconsole.ico')
    expect(packageJson.build.nsis.uninstallerIcon).toBe('../../resources/branding/netconsole.ico')
    expect(packageJson.build.nsis.installerHeaderIcon).toBe('../../resources/branding/netconsole.ico')
    expect(packageJson.build.nsis.deleteAppDataOnUninstall).toBe(false)
    expect(packageJson.build.nsis.perMachine).toBe(true)
    expect(packageJson.build.nsis.include).toBe('build/installer-data-root.nsh')
    expect(packageJson.build.win.target[0]).toEqual({ target: 'nsis', arch: ['x64'] })
  })

  it('adds a separate, validated business-data-root page to the existing NSIS installer', () => {
    const script = readFileSync(resolve(appRoot, 'build', 'installer-data-root.nsh'), 'utf8')

    expect(script).toContain('Page custom NetConsoleDataRootPageCreate NetConsoleDataRootPageLeave')
    expect(script).toContain('选择 NetConsole 数据存放位置')
    expect(script).toContain('GetDriveTypeW')
    expect(script).toContain('禁止将业务数据存放在系统盘')
    expect(script).toContain('storage-manifest.json')
    expect(script).toContain('NetConsoleDataRootChanged')
    expect(script).toContain('--migrate-data-root')
    expect(script).toContain('--validate-data-root')
    expect(script).toContain('WriteRegStr HKLM "Software\\NetConsole" "DataRoot"')
    expect(script).not.toContain('DeleteRegKey HKLM "Software\\NetConsole"')
  })

  it('resolves the packaged executable from the Electron Builder contract', () => {
    const script = resolve(appRoot, 'scripts', 'package-smoke.mjs')
    const packageJsonPath = resolve(appRoot, 'package.json')
    const configured = spawnSync(
      process.execPath,
      [script, '--resolve-windows-executable', packageJsonPath],
      { cwd: appRoot, encoding: 'utf8' },
    )

    expect(configured.status, configured.stdout + configured.stderr).toBe(0)
    expect(configured.stdout.trim()).toBe('NetConsole.exe')

    const temporary = mkdtempSync(join(tmpdir(), 'netconsole-electron-package-contract-'))
    const invalidPackageJsonPath = resolve(temporary, 'package.json')
    try {
      writeFileSync(invalidPackageJsonPath, JSON.stringify({ build: { win: {} } }), 'utf8')
      const missing = spawnSync(
        process.execPath,
        [script, '--resolve-windows-executable', invalidPackageJsonPath],
        { cwd: appRoot, encoding: 'utf8' },
      )

      expect(missing.status, missing.stdout + missing.stderr).not.toBe(0)
      expect(missing.stderr).toContain('build.win.executableName')
    } finally {
      rmSync(temporary, { recursive: true, force: true })
    }
  })

  it('builds the backend without a system Python dependency', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package.mjs'), 'utf8')

    expect(script).toContain('scripts.build.build_release')
    expect(script).toContain('scripts.build.check_runtime_deps')
    expect(script).toContain('--locked-environment')
    expect(script).toContain('constraints.txt')
    expect(script).toContain('NetConsoleBackend.exe')
    expect(script).toContain("'.venv', 'Scripts', 'python.exe'")
    expect(script).toContain("'--release'")
  })

  it('scans the packaged app for forbidden Qt runtime files', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8').toLowerCase()

    for (const marker of [
      'pyside2',
      'pyside6',
      'pyqt5',
      'pyqt6',
      'shiboken2',
      'shiboken6',
      'qfluentwidgets',
      'qt[56]',
      'qtwebengineprocess.exe',
      'qt.conf',
      'sip.pyd',
      'qwindows.dll',
      'qwindowsd.dll',
    ]) {
      expect(script).toContain(marker)
    }
    expect(script).toContain('netconsole_electron_smoke_test'.toLowerCase())
  })

  it('requires the packaged production feature baseline', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain('requiredProductionFeatureIds')
    expect(script).toContain('web.device_management_collect')
    expect(script).toContain('web.online_mr_analysis')
    expect(script).toContain('web.mesh_analysis_import')
    expect(script).toContain('Electron 包生产功能基线关闭必要能力')
  })

  it('compares packaged build metadata with the actual Git HEAD', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain('build-metadata.json')
    expect(script).toContain("['-C', projectRoot, 'rev-parse', 'HEAD']")
    expect(script).toContain('metadata.build_dirty !== false')
    expect(script).toContain('frontend.git_commit_full')
    expect(script).toContain('PACKAGED_BACKEND_COMMIT=')
    expect(script).toContain('PACKAGED_FRONTEND_COMMIT=')
  })

  it('requires runtime-versioned NOTICE and a strict CycloneDX SBOM', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8').toLowerCase()

    expect(script).toContain('open_source_notices.json')
    expect(script).toContain('third_party_components.md')
    expect(script).toContain('sbom.cdx.json')
    expect(script).toContain('electron')
    expect(script).toContain('chromium')
    expect(script).toContain('node.js')
    expect(script).toContain('cygwin runtime')
    expect(script).toContain('iperf3 windows x64 cygwin dynamic-auth')
    expect(script).toContain('openssl runtime (iperf3 bundle)')
    expect(script).toContain('zlib runtime (iperf3 bundle)')
    expect(script).toContain('electron_run_as_node')
    expect(script).toContain('license.electron.txt')
    expect(script).toContain('licenses.chromium.html')
    expect(script).toContain('bom-ref')
    expect(script).toContain('purl')
    expect(script).toContain('unknown')
    expect(script).toContain('pyinstaller-artifact-inventory.json')
    expect(script).toContain('pyinstaller-approved-distributions.json')
    expect(script).toContain('netconsole.pyinstaller-artifact-inventory.v1')
    expect(script).toContain('netconsole.pyinstaller-approved-distributions.v1')
    expect(script).toContain('pyinstaller_copying.txt')
    expect(script).toContain('pyinstaller_hooks_contrib_license.txt')
    expect(script).toContain('netconsolebackend.exe')
  })

  it('pins the approved iPerf3 3.21 dynamic-auth asset and licenses', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8').toLowerCase()

    expect(script).toContain('iperf-3.21-win64-dynamic-auth.zip')
    expect(script).toContain('0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb')
    for (const name of ['iperf3.exe', 'cygwin1.dll', 'cygcrypto-3.dll', 'cygz.dll']) {
      expect(script).toContain(name)
    }
    for (const name of ['ar51an_apache-2.0.txt', 'iperf3_license.txt', 'gpl-3.0.txt', 'cygwin_lgpl-3.0.txt', 'openssl_apache-2.0.txt', 'zlib_license.txt']) {
      expect(script).toContain(name)
    }
    expect(script).toContain('cygwin-3.6.7-1-src.tar.xz')
    expect(script).toContain('corresponding_source.md')
  })

  it('pins the actual patched fping build and Cygwin corresponding source', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8').toLowerCase()

    expect(script).toContain('v5.5-dirty')
    expect(script).toContain('cygwin_icmp_compat.patch')
    expect(script).toContain('build_recipe.md')
    expect(script).toContain('cygwin-3.6.9-1-src.tar.xz')
    expect(script).toContain('gpl-3.0.txt')
  })

  it('rejects duplicate, incomplete, tampered, or missing local tool provenance', () => {
    const script = resolve(appRoot, 'scripts', 'package-smoke.mjs')
    const source = resolve(appRoot, '..', '..', 'resources', 'tools', 'windows-x64')
    const mutations: Array<(root: string) => void> = [
      (root) => rewriteProvenance(root, 'iperf3', (payload) => {
        payload.files.unshift({ ...payload.files[0] })
      }),
      (root) => rewriteProvenance(root, 'iperf3', (payload) => {
        payload.files[0].version = '999'
      }),
      (root) => rewriteProvenance(root, 'iperf3', (payload) => {
        payload.unapproved = true
      }),
      (root) => rewriteProvenance(root, 'iperf3', (payload) => {
        payload.upstream_sources[2] = { name: 'OpenSSL Cygwin Runtime' }
      }),
      (root) => unlinkSync(resolve(root, 'fping', 'README.txt')),
    ]

    for (const mutate of mutations) {
      const temporary = mkdtempSync(join(tmpdir(), 'netconsole-electron-tool-guard-'))
      const toolRoot = resolve(temporary, 'windows-x64')
      try {
        cpSync(source, toolRoot, { recursive: true })
        mutate(toolRoot)
        const result = spawnSync(
          process.execPath,
          [script, '--validate-tool-root', toolRoot],
          { cwd: appRoot, encoding: 'utf8' },
        )
        expect(result.status, result.stdout + result.stderr).not.toBe(0)
      } finally {
        rmSync(temporary, { recursive: true, force: true })
      }
    }
  })

  it('validates the packaged device inventory command profile', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain('device_command_profiles.json')
    expect(script).toContain('2026.07.device-command-profiles.v1')
    expect(script).toContain('device.inventory.collect')
    for (const command of [
      'screen-length disable',
      'display current-configuration | include sysname',
      'display version',
      'display device',
      'display device manuinfo',
      'display boot-loader',
      'display interface',
      'display transceiver interface',
      'display transceiver manuinfo interface',
      'display transceiver diagnosis interface',
      'display lldp neighbor-information list',
      'display lldp neighbor-information verbose',
    ]) {
      expect(script).toContain(command)
    }
  })
})

function rewriteProvenance(
  root: string,
  tool: 'iperf3' | 'fping',
  mutate: (payload: any) => void,
) {
  const path = resolve(root, tool, 'SOURCE_PROVENANCE.json')
  const payload = JSON.parse(readFileSync(path, 'utf8'))
  mutate(payload)
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
}
