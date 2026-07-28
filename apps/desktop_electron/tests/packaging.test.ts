import { cpSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

import { describe, expect, it } from 'vitest'

const appRoot = resolve(import.meta.dirname, '..')

describe('Electron-only packaging', () => {
  it('packages the managed backend and preserves user data on uninstall', () => {
    const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))

    expect(packageJson.scripts.package).toContain('build-installer.mjs')
    expect(packageJson.scripts['smoke:package']).toContain('package-smoke.mjs')
    expect(packageJson.build.productName).toBe('NetConsole v1.4.4 by wxj')
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
    expect(packageJson.build.nsis.unicode).toBe(true)
    expect(packageJson.build.win.target[0]).toEqual({ target: 'nsis', arch: ['x64'] })
  })

  it('builds a unique commit-named installer through the final EXE gate', () => {
    const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))
    const launcher = readFileSync(resolve(appRoot, 'scripts', 'build-installer.mjs'), 'utf8')
    const builder = readFileSync(resolve(appRoot, '..', '..', 'scripts', 'build', 'build_installer.py'), 'utf8')

    expect(packageJson.scripts.package).toBe('node scripts/build-installer.mjs')
    expect(launcher).toContain('scripts.build.build_installer')
    expect(builder).toContain('NetConsole-{app_version}-{short}-x64-setup.exe')
    expect(builder).toContain('electron-builder')
    expect(builder).toContain('--config.win.artifactName=')
    expect(builder).toContain('SubType = NSIS-3 Unicode')
    expect(builder).toContain('InstallerGitCommit')
    expect(builder).toContain('installer_policy_source_sha256')
    expect(builder).toContain('real_windows_install_status')
  })

  it('adds a separate, validated business-data-root page to the existing NSIS installer', () => {
    const script = readFileSync(resolve(appRoot, 'build', 'installer-data-root.nsh'), 'utf8')

    expect(script).toContain('Page custom NetConsoleDataRootPageCreate NetConsoleDataRootPageLeave')
    expect(script).toContain('!ifndef BUILD_UNINSTALLER')
    expect(script).toContain('选择 NetConsole 数据存放位置')
    expect(script).toContain('GetDriveTypeW')
    expect(script).toContain('禁止将业务数据存放在系统盘')
    expect(script).toContain('storage-manifest.json')
    expect(script).toContain('NetConsoleDataRootChanged')
    expect(script).toContain('--migrate-data-root')
    expect(script).toContain('--validate-data-root')
    expect(script).toContain('creates/checks the storage')
    expect(script).toContain('Backend 数据根初始化或兼容性校验失败')
    expect(script).toContain('Function NetConsoleDataRootCheckEntries')
    expect(script).toContain('FindFirst $NetConsoleDataRootFindHandle $NetConsoleDataRootFindName "$NetConsoleDataRoot\\*"')
    expect(script).toContain('FindNext $NetConsoleDataRootFindHandle $NetConsoleDataRootFindName')
    expect(script).toContain('StrCmp $NetConsoleDataRootFindName "."')
    expect(script).toContain('StrCmp $NetConsoleDataRootFindName ".."')
    expect(script).toContain('StrCmp $NetConsoleDataRootFindName ".netconsole-installer-write-test.tmp"')
    expect(script).toContain('StrCmp $NetConsoleDataRootFindName ".netconsole-installer-rename-test.tmp"')
    expect(script).not.toContain('StrCpy $NetConsoleDataRoot "$NetConsoleDataRoot\\NetConsoleData"')
    expect(script).not.toContain('是否在其中创建 NetConsoleData 子目录')

    const leaveFunction = script.slice(script.indexOf('Function NetConsoleDataRootPageLeave'))
    const locationIndex = leaveFunction.indexOf('Call NetConsoleValidateDataRootLocation')
    const classifyIndex = leaveFunction.indexOf('Call NetConsoleDataRootCheckEntries')
    const probeIndex = leaveFunction.indexOf('Call NetConsoleRunDataRootProbe')
    expect(locationIndex).toBeGreaterThan(-1)
    expect(classifyIndex).toBeGreaterThan(-1)
    expect(probeIndex).toBeGreaterThan(classifyIndex)
    expect(leaveFunction.slice(probeIndex)).not.toContain('Call NetConsoleDataRootCheckEntries')
    const locationFunction = script.slice(
      script.indexOf('Function NetConsoleValidateDataRootLocation'),
      script.indexOf('Function NetConsoleDataRootCheckEntries'),
    )
    expect(locationFunction).toContain("System::Call 'kernel32::GetDriveTypeW(w r1)i.r2'")
    expect(locationFunction).not.toContain("System::Call 'kernel32::GetDriveTypeW(w r0)i.r1'")
    expect(locationFunction).toContain('Call NetConsoleNormalizeDataRootPath')
    expect(locationFunction).not.toContain('GetFullPathName $NetConsoleDataRootNormalized')
    const normalizer = script.slice(
      script.indexOf('Function NetConsoleNormalizeDataRootPath'),
      script.indexOf('Function NetConsoleDataRootCheckEntries'),
    )
    expect(normalizer).toContain("kernel32::GetFullPathNameW")
    expect(normalizer).toContain('${NSIS_MAX_STRLEN}')
    expect(normalizer).toContain('NC_PATH_NOT_ABSOLUTE')
    expect(normalizer).toContain('NC_PATH_INVALID_CHARACTER')
    expect(normalizer).not.toContain('GetFullPathName $NetConsoleDataRootNormalized')
    expect(script).toContain('GetDriveTypeW accepts a root path such as E:\\, never E:\\NetConsoleData')
    expect(script).toContain('DataRoot selected path: $NetConsoleDataRoot')
    expect(script).toContain('DataRoot normalized path: $NetConsoleDataRootNormalized')
    expect(script).toContain('DataRoot drive root: $NetConsoleDataRootDriveRoot')
    expect(script).toContain('DataRoot GetDriveTypeW: $NetConsoleDataRootDriveType')
    expect(script).toContain('DataRoot existing entry: $NetConsoleDataRootFindName')
    expect(script).toContain('目录包含现有普通文件')
    expect(script).not.toContain('所选目录非空且不是已识别的 NetConsole 数据根')
    expect(script).toContain('!macro customHeader')
    expect(script).toContain('VIAddVersionKey /LANG=1033 "InstallerGitCommit"')
    expect(script).toContain('VIAddVersionKey /LANG=1033 "InstallerBuildId"')
    expect(script).toContain('VIAddVersionKey /LANG=1033 "InstallerPolicySHA256"')
    expect(script).toContain('netconsole-installer-build.json')
    expect(script).toContain('netconsole-installer-data-root.nsh')
    expect(script).toContain('安装器：v${NETCONSOLE_INSTALLER_APP_VERSION}')
    expect(script).toContain('WriteRegStr HKLM "Software\\NetConsole" "DataRoot"')
    expect(script).not.toContain('DeleteRegKey HKLM "Software\\NetConsole"')
  })

  it('probes rename support with a unique file inside the selected data root', () => {
    const script = readFileSync(resolve(appRoot, 'build', 'installer-data-root.nsh'), 'utf8')
    const probeFunction = script.slice(
      script.indexOf('Function NetConsoleRunDataRootProbe'),
      script.indexOf('Function NetConsoleDataRootPageLeave'),
    )
    const closeIndex = script.indexOf('FileClose $0')
    const renameIndex = script.indexOf('MoveFileExW(w "$NetConsoleDataRootProbeSource", w "$NetConsoleDataRootProbeTarget"')

    expect(script).toContain('.netconsole-install-probe-$NetConsoleDataRootProbePid-$NetConsoleDataRootProbeTick.tmp')
    expect(script).toContain('GetCurrentProcessId')
    expect(script).toContain('GetTickCount')
    expect(script).toContain('FlushFileBuffers')
    expect(script).toContain('NetConsole-install-probe-v1')
    expect(closeIndex).toBeGreaterThan(-1)
    expect(renameIndex).toBeGreaterThan(closeIndex)
    expect(script).toContain('FileRead $0 $NetConsoleDataRootProbeActual')
    expect(script).toContain('Delete "$NetConsoleDataRootProbeTarget"')
    expect(script).toContain('错误来源：$NetConsoleDataRootProbeErrorSource')
    expect(script).toContain('错误码：$NetConsoleDataRootProbeErrorCode')
    expect(script).toContain('目录不可写（访问被拒绝）')
    expect(script).toContain('临时探测文件正在被其他程序占用')
    expect(script).toContain('文件系统不支持同目录文件重命名')
    expect(script).not.toContain('StrCpy $NetConsoleDataRootProbeSource "$NetConsoleDataRoot\\.netconsole-installer-write-test.tmp"')
    expect(script).not.toContain('StrCpy $NetConsoleDataRootProbeTarget "$NetConsoleDataRoot\\.netconsole-installer-rename-test.tmp"')
    expect(script).not.toContain('Delete "$NetConsoleDataRoot\\.netconsole-installer-write-test.tmp"')
    expect(script).not.toContain('Delete "$NetConsoleDataRoot\\.netconsole-installer-rename-test.tmp"')
    expect(script).not.toContain('Rename "$NetConsoleDataRoot"')
    expect(script).not.toContain('MoveFileExW(w "$NetConsoleDataRoot"')
    expect(probeFunction).not.toContain('$TEMP')
    expect(probeFunction).not.toContain('$PLUGINSDIR')
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

  it('runs the packaged Electron smoke only in a unique D-drive test root', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain("const WINDOWS_TEST_DATA_ROOT = 'D:\\\\NetConsoleTestData'")
    expect(script).toContain("mkdtempSync(join(WINDOWS_TEST_DATA_ROOT, 'NetConsole-package-smoke-'))")
    expect(script).toContain("NETCONSOLE_RUNTIME_MODE: 'test'")
    expect(script).toContain("NETCONSOLE_STORAGE_MODE: 'isolated_test'")
    expect(script).not.toContain("mkdtempSync(join(tmpdir(), 'NetConsole-Codex-package-smoke-'))")
  })

  it('requests the frozen Backend ground unattended status with packaged tzdata', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain('validateFrozenTimezoneResources')
    expect(script).toContain('validateFrozenGroundUnattendedStatus')
    expect(script).toContain("PYTHONTZPATH: ''")
    expect(script).toContain('/api/rail-transit/ground-unattended/status')
    expect(script).toContain("payload?.timezone !== 'Asia/Shanghai'")
    expect(script).toContain('for (let attempt = 1; attempt <= 2; attempt += 1)')
    expect(script).toContain('assertLoopbackPortReleased')
    expect(script).toContain('ground unattended status HTTP 200')
  })

  it('prepares MESH context and verifies duplicate-safe archive imports through the frozen Backend', () => {
    const script = readFileSync(resolve(appRoot, 'scripts', 'package-smoke.mjs'), 'utf8')

    expect(script).toContain('/api/device-management/groups')
    expect(script).toContain('/api/device-management/devices')
    expect(script).toContain('列车34-MR-CT')
    expect(script).toContain('列车34-MR-CW')
    expect(script).toContain('/api/rail-transit/mesh-analysis/profiles')
    expect(script).toContain('/api/rail-transit/mesh-analysis/import-context/prepare')
    expect(script).toContain('firstPrepare.created_count !== createdProfileCount')
    expect(script).toContain('createdProfileCount < 2')
    expect(script).toContain('secondPrepare.created_count !== 0')
    expect(script).toContain('/api/rail-transit/mesh-analysis/import-preview')
    expect(script).toContain('/api/online-mr/tasks/')
    expect(script).toContain('/api/tasks/')
    expect(script).toContain('2026_07_28_1meshlog.log')
    expect(script).toContain("duplicateItem?.duplicate_status !== 'duplicate_same_mr'")
    expect(script).toContain('sessionsAfterDuplicate.total !== 1')
    expect(script).toContain('MESH import context idempotency and duplicate-safe archive naming')
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
    expect(script).toContain("'tzdata'")
    expect(script).toContain('zoneinfofiles.length !== 604')
    expect(script).toContain('tzdata/zoneinfo/asia/shanghai')
    expect(script).toContain('tzdata/zoneinfo/utc')
    expect(script).toContain('tzdata/zoneinfo/europe/bucharest')
    expect(script).toContain('tzdata/zoneinfo/america/new_york')
    expect(script).toContain('tzdata/zoneinfo/tzdata.zi')
    expect(script).toContain('tzdata/zoneinfo/zone1970.tab')
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
