import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { isDeepStrictEqual } from 'node:util'

const appRoot = resolve(import.meta.dirname, '..')
const projectRoot = resolve(appRoot, '..', '..')
const unpackedRoot = resolve(projectRoot, 'dist', 'electron', 'win-unpacked')
const qtPackagePrefixes = [
  'pyside2',
  'pyside6',
  'pyqt5',
  'pyqt6',
  'shiboken2',
  'shiboken6',
  'qfluentwidgets',
  'pyqt-fluent-widgets',
  'pyside2-fluent-widgets',
  'pyside6-fluent-widgets',
  'sip',
]
const qtBasenames = new Set([
  'qwindows.dll',
  'qwindowsd.dll',
  'qminimal.dll',
  'qminimald.dll',
  'qoffscreen.dll',
  'qoffscreend.dll',
  'qgif.dll',
  'qgifd.dll',
  'qico.dll',
  'qicod.dll',
  'qjpeg.dll',
  'qjpegd.dll',
  'qsvg.dll',
  'qsvgd.dll',
  'qsvgicon.dll',
  'qsvgicond.dll',
  'qtga.dll',
  'qtgad.dll',
  'qtiff.dll',
  'qtiffd.dll',
  'qwbmp.dll',
  'qwbmpd.dll',
  'qwebp.dll',
  'qwebpd.dll',
  'sip.pyd',
  'sip.dll',
  'sip.so',
  'qtwebengineprocess.exe',
  'qt.conf',
])
const qtLibraryPattern = /^(?:lib)?qt[56][a-z0-9_.-]*\.(?:dll|pyd|so|dylib)$/i
const qtPythonExtensionPattern = /^qt(?:core|gui|widgets|network|qml|quick|svg|webengine|webchannel|websockets|opengl|printsupport)\.(?:pyd|so)$/i
const qtTranslationPattern = /^qt(?:base|declarative|quickcontrols|webengine)?_[a-z0-9_-]+\.qm$/i
const requiredComponentNames = [
  'python',
  'electron',
  'chromium',
  'node.js',
  'fping',
  'iperf3 windows x64 cygwin dynamic-auth',
  'cjson (embedded in iperf3)',
  'cygwin runtime (fping bundle)',
  'cygwin runtime (iperf3 bundle)',
  'openssl runtime (iperf3 bundle)',
  'zlib runtime (iperf3 bundle)',
  'websockets',
  'pyinstaller',
  'pyinstaller-hooks-contrib',
]
const expectedPackagedPythonLicenses = {
  pyinstaller: {
    file: 'PYINSTALLER_COPYING.txt',
    sha256: 'dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245',
  },
  'pyinstaller-hooks-contrib': {
    file: 'PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt',
    sha256: '91d0baaff00773038e72c0a1fc9d5d2d38706b7a2b9c04f34296608f931b9cd0',
  },
}
const expectedIperfFiles = {
  'iperf3.exe': '4aae5eee2b90c716d93bdc54c530a854596c92ff996859973b9f44e73799294e',
  'cygwin1.dll': '0ab76b4724499df54b75b7fa701788f1e77425ce65c8bca0a9f2120598bb8a70',
  'cygcrypto-3.dll': '3cfcab214b827485265c21f5c365af5055ee47ca507cc56a1422661288d51ea6',
  'cygz.dll': '827576482185c48ed3698454594260ee27ba32180127b8ba28c5ca68a867ce38',
}
const expectedIperfLicenseFiles = {
  'AR51AN_APACHE-2.0.txt': 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4',
  'CYGWIN_LGPL-3.0.txt': 'e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118',
  'CYGWIN_LINKING_EXCEPTION.txt': '794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984',
  'GPL-3.0.txt': '0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227',
  'IPERF3_LICENSE.txt': '6c6e9abd761ff429c11189cd93bdee5bff7e3591253bd614b253a5f4fd30cbe5',
  'OPENSSL_APACHE-2.0.txt': '7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a',
  'ZLIB_LICENSE.txt': 'e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2',
}
const expectedFpingFiles = {
  'fping.exe': '9c9ab2f26d3d32818b53ed7b664ec53546fc5cd59f4d953e06f9d3e28673f9d9',
  'cygwin1.dll': 'd5562774ec1475bd1dab84c5249b273e60cc53e6aa968981414a4d6a3f8e2bfd',
}
const expectedFpingLicenseFiles = {
  COPYING: '6051b27e4b4a648f7bc8b329024da53a6e95ce88fcf0ccc259c371a74b741757',
  'COPYING.LIB': '1a45b1d0a8603dfe2cfc644f9dab970b1762f92babe2aac6eb2f5d4572c4a680',
  'GPL-3.0.txt': '0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227',
  CYGWIN_LICENSE: '794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984',
  'CYGWIN_LICENSE_NOTE.txt': '39872eccdbdb5ed0952e2bf175532227defa3fc97fec69a96a7fef744535fbf4',
}
const expectedFpingComplianceFiles = {
  'BUILD_RECIPE.md': 'e1019b55830d91a97314b26985193b254507b3495f225681cc101288fa1ca1f5',
  'CORRESPONDING_SOURCE.md': 'a0ca3f1e13af8ad8ae66ad5c2db7c11faba3b9392ca9c1426856ae476b9f22f3',
  'CYGWIN_ICMP_COMPAT.patch': 'f245e88cbc111d4bc3476c1146713cc1462fff5011baf41926f2dfdabb30bf83',
}
const expectedIperfComplianceFiles = {
  'CORRESPONDING_SOURCE.md': 'faea146cd105ffb781c188e6b9576691cf7f4a37ba033226007b37410669e468',
  'licenses/README.md': '31d120a478c8d5f245b31fba5e74f9cc5960dc801907b9dee370da4157820909',
}
const expectedIperfFileEntries = {
  'iperf3.exe': { name: 'iperf3.exe', version: '3.21', sha256: expectedIperfFiles['iperf3.exe'] },
  'cygwin1.dll': { name: 'cygwin1.dll', version: '3.6.7-1', sha256: expectedIperfFiles['cygwin1.dll'] },
  'cygcrypto-3.dll': { name: 'cygcrypto-3.dll', version: '3.0.19', sha256: expectedIperfFiles['cygcrypto-3.dll'] },
  'cygz.dll': { name: 'cygz.dll', version: '1.3.2', sha256: expectedIperfFiles['cygz.dll'] },
}
const expectedFpingFileEntries = {
  'fping.exe': { name: 'fping.exe', version: '5.5', sha256: expectedFpingFiles['fping.exe'] },
  'cygwin1.dll': { name: 'cygwin1.dll', version: '3.6.9-1', sha256: expectedFpingFiles['cygwin1.dll'] },
}
const expectedIperfUpstreamSources = {
  iperf3: {
    name: 'iperf3',
    version: '3.21',
    repository: 'https://github.com/esnet/iperf',
    tag: '3.21',
    tag_object: 'ec66336d2c152bf964f671e9e20a11de05edb239',
    tag_commit: 'd39cf41526626b4e5a130f115d931cd6cbdffc19',
    license_file: 'licenses/IPERF3_LICENSE.txt',
  },
  'Cygwin Runtime': {
    name: 'Cygwin Runtime',
    version: '3.6.7-1',
    source_package: 'cygwin-3.6.7-1-src',
    source_index: 'https://cygwin.com/packages/summary/cygwin-src.html',
    source_contents: 'https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.7-1-src',
    source_archive_path: 'src/release/cygwin/cygwin-3.6.7-1-src.tar.xz',
    source_archive_size: 9309160,
    source_archive_sha512: '82a190c3516511af7d1305e1bcd4aa0177c1fb584b6468a887a9119565bccd88630b2a3b826d902983a83adefb11545346dcf27616186304d6c66879e1647335',
    license_file: 'licenses/CYGWIN_LGPL-3.0.txt',
    gpl_file: 'licenses/GPL-3.0.txt',
    exception_file: 'licenses/CYGWIN_LINKING_EXCEPTION.txt',
  },
  'OpenSSL Cygwin Runtime': {
    name: 'OpenSSL Cygwin Runtime',
    version: '3.0.19-1',
    source_index: 'https://cygwin.com/packages/summary/openssl-src.html',
    license_file: 'licenses/OPENSSL_APACHE-2.0.txt',
  },
  'zlib Cygwin Runtime': {
    name: 'zlib Cygwin Runtime',
    version: '1.3.2-1',
    source_index: 'https://cygwin.com/packages/summary/zlib-src.html',
    license_file: 'licenses/ZLIB_LICENSE.txt',
  },
}
const expectedFpingUpstreamSources = {
  fping: {
    name: 'fping',
    version: '5.5',
    repository: 'https://github.com/schweikert/fping',
    tag: 'v5.5',
    tag_commit: '06f9481ef3cf79c2aa973718366fb13927777689',
  },
  'Cygwin Runtime': {
    name: 'Cygwin Runtime',
    version: '3.6.9-1',
    source_package: 'cygwin-3.6.9-1-src',
    source_index: 'https://cygwin.com/packages/summary/cygwin-src.html',
    source_contents: 'https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.9-1-src',
    source_archive_path: 'src/release/cygwin/cygwin-3.6.9-1-src.tar.xz',
    source_archive_size: 9312760,
    source_archive_sha512: '771ab64fff17323a32b7cb56140c974d446899a5d4eb5b76115e14cd8fe2e4108be5f30112e441def0f86666d37ab35ba5fb31950910d91ffc12ba69e0934f6e',
    repository: 'https://cygwin.com/git/newlib-cygwin.git',
    tag: 'cygwin-3.6.9',
    tag_object: 'f802d89cdc3fbbfbb47f5a6b3a4e27b7a2363795',
    tag_commit: 'daabea98682f3f4bef0044829a8d24226135bb71',
  },
}
const allowedIperfFiles = new Set([
  ...Object.keys(expectedIperfFiles),
  'README.md',
  'SOURCE_PROVENANCE.json',
  ...Object.keys(expectedIperfComplianceFiles),
  ...Object.keys(expectedIperfLicenseFiles).map((name) => `licenses/${name}`),
])
const allowedFpingFiles = new Set([
  ...Object.keys(expectedFpingFiles),
  ...Object.keys(expectedFpingLicenseFiles),
  ...Object.keys(expectedFpingComplianceFiles),
  'README.md',
  'README.txt',
  'SOURCE_PROVENANCE.json',
  'VERSION.txt',
])
const expectedDeviceInventoryCommands = [
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
]
const expectedMobileRouterDeviceInventoryCommands = [
  'screen-length disable',
  'display current-configuration | include sysname',
  'display version',
  'display device',
  'display device manuinfo',
  'display boot-loader',
  'display interface',
]
const expectedDeviceInventoryProfiles = new Map([
  ['h3c.comware.switch.generic.device-inventory.v1', expectedDeviceInventoryCommands],
  ['h3c.comware.mobile_router.generic.device-inventory.v1', expectedMobileRouterDeviceInventoryCommands],
])

const executableNameArgument = process.argv.indexOf('--resolve-windows-executable')
if (executableNameArgument >= 0) {
  const packageJsonPath = process.argv[executableNameArgument + 1]
  if (!packageJsonPath) throw new Error('--resolve-windows-executable 必须提供 package.json 路径。')
  console.log(resolveWindowsExecutableName(resolve(packageJsonPath)))
  process.exit(0)
}

const executable = resolve(unpackedRoot, resolveWindowsExecutableName(resolve(appRoot, 'package.json')))
const toolRootArgument = process.argv.indexOf('--validate-tool-root')
if (toolRootArgument >= 0) {
  const toolRoot = process.argv[toolRootArgument + 1]
  if (!toolRoot) throw new Error('--validate-tool-root 必须提供工具根目录。')
  validateIperfDistribution(resolve(toolRoot, 'iperf3'))
  validateFpingDistribution(resolve(toolRoot, 'fping'))
  console.log('Electron runtime tool guard passed with an exact local-only manifest.')
  process.exit(0)
}

const residue = walk(unpackedRoot).filter((path) => {
  return isQtResidue(relative(unpackedRoot, path))
})
if (residue.length) throw new Error(`Electron 包检测到 Qt 残留：${residue.slice(0, 20).join(', ')}`)

validateDeviceCommandProfiles()
validateIperfDistribution()
validateFpingDistribution()
const runtimeVersions = readElectronRuntimeVersions()
validateComplianceArtifacts(runtimeVersions)

const smokeRoot = mkdtempSync(join(tmpdir(), 'NetConsole-Codex-package-smoke-'))
const smokeDataRoot = resolve(smokeRoot, 'data')
const smokeUserDataRoot = resolve(smokeRoot, 'electron-user-data')
mkdirSync(smokeDataRoot, { recursive: true })
mkdirSync(smokeUserDataRoot, { recursive: true })
try {
  const result = spawnSync(
    executable,
    [`--user-data-dir=${smokeUserDataRoot}`],
    {
      cwd: unpackedRoot,
      env: {
        ...process.env,
        NETCONSOLE_DATA_ROOT: smokeDataRoot,
        NETCONSOLE_STORAGE_MODE: 'isolated_test',
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DEV_TEMP_USER_DATA_ROOT: smokeUserDataRoot,
        NETCONSOLE_ELECTRON_SMOKE_TEST: '1',
      },
      stdio: 'inherit',
      timeout: 45_000,
      windowsHide: true,
    },
  )
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`Electron packaged smoke failed with exit code ${result.status}`)
} finally {
  rmSync(smokeRoot, { recursive: true, force: true })
}

console.log('Electron packaged smoke passed without Qt runtime residue and with NOTICE/SBOM metadata.')

function resolveWindowsExecutableName(packageJsonPath) {
  const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf8'))
  const executableName = packageJson?.build?.win?.executableName
  if (typeof executableName !== 'string' || !executableName.trim()) {
    throw new Error(
      `Electron Builder 构建契约错误：${packageJsonPath} 必须设置 build.win.executableName。`,
    )
  }
  return `${executableName.trim()}.exe`
}

function validateComplianceArtifacts(runtimeVersions) {
  const backendRoot = resolve(unpackedRoot, 'resources', 'backend')
  const noticePath = resolve(backendRoot, '_internal', 'netconsole', 'assets', 'open_source_notices.json')
  const componentsPath = resolve(backendRoot, '_internal', 'netconsole', 'assets', 'THIRD_PARTY_COMPONENTS.md')
  const sbomPath = resolve(backendRoot, '_internal', 'netconsole', 'assets', 'sbom.cdx.json')
  const notices = JSON.parse(readFileSync(noticePath, 'utf8'))
  const sbom = JSON.parse(readFileSync(sbomPath, 'utf8'))
  const packagedLicenseRoot = resolve(backendRoot, '_internal', 'netconsole', 'assets', 'licenses')
  if (!readFileSync(resolve(unpackedRoot, 'LICENSE.electron.txt'), 'utf8').trim()) {
    throw new Error('Electron 包缺少 Electron LICENSE 文本。')
  }
  if (!readFileSync(resolve(unpackedRoot, 'LICENSES.chromium.html'), 'utf8').trim()) {
    throw new Error('Electron 包缺少 Chromium 第三方许可证文本。')
  }
  if (!readFileSync(componentsPath, 'utf8').trim()) throw new Error('Electron 包缺少第三方组件说明。')
  const unknownLicenses = new Set(['', 'unknown', 'unknown license', 'not declared', '未在包元数据中声明'])
  const unknown = notices.filter((item) => unknownLicenses.has(String(item.license ?? '').trim().toLowerCase()) || String(item.status ?? '').toLowerCase() === 'blocked')
  if (unknown.length) throw new Error(`Electron 包存在未知许可证：${unknown.map((item) => item.name).join(', ')}`)
  const noticeNames = new Set(notices.map((item) => String(item.name).toLowerCase()))
  for (const required of requiredComponentNames) {
    if (!noticeNames.has(required)) throw new Error(`Electron 包 NOTICE 缺少 ${required}。`)
  }
  for (const [name, expected] of Object.entries(expectedPackagedPythonLicenses)) {
    const notice = notices.find((item) => String(item.name).toLowerCase() === name)
    if (
      !notice
      || !Array.isArray(notice.license_files)
      || notice.license_files.length !== 1
      || notice.license_files[0] !== `licenses/${expected.file}`
    ) {
      throw new Error(`Electron 包 NOTICE 的 ${name} 许可证清单不精确。`)
    }
    if (sha256(resolve(packagedLicenseRoot, expected.file)) !== expected.sha256) {
      throw new Error(`Electron 包 ${name} 许可证文本哈希不匹配。`)
    }
  }
  validateRuntimeVersion(notices, 'Electron', runtimeVersions.electron)
  validateRuntimeVersion(notices, 'Chromium', runtimeVersions.chrome)
  validateRuntimeVersion(notices, 'Node.js', runtimeVersions.node)
  if (sbom.bomFormat !== 'CycloneDX' || sbom.specVersion !== '1.5' || !Number.isInteger(sbom.version) || sbom.version < 1 || !Array.isArray(sbom.components)) {
    throw new Error('Electron 包缺少有效 CycloneDX 1.5 SBOM。')
  }
  const sbomNames = new Set(sbom.components.map((item) => String(item.name).toLowerCase()))
  for (const required of requiredComponentNames) {
    if (!sbomNames.has(required)) throw new Error(`Electron 包 SBOM 缺少 ${required}。`)
  }
  for (const item of sbom.components) {
    const licenses = Array.isArray(item.licenses) ? item.licenses : []
    const licenseValues = licenses.map((entry) => String(entry.expression ?? entry.license?.id ?? entry.license?.name ?? '').trim().toLowerCase())
    if (!item.name || !item.version || !item['bom-ref'] || !item.purl || validatePurl(String(item.purl)) || item['bom-ref'] !== item.purl || !licenseValues.length || licenseValues.some((value) => unknownLicenses.has(value))) {
      throw new Error(`Electron 包 SBOM 组件缺少许可证：${item.name ?? '<unknown>'}`)
    }
  }
  validateRuntimeVersion(sbom.components, 'Electron', runtimeVersions.electron)
  validateRuntimeVersion(sbom.components, 'Chromium', runtimeVersions.chrome)
  validateRuntimeVersion(sbom.components, 'Node.js', runtimeVersions.node)
  validatePythonArtifactInventory(backendRoot, sbom)
}

function validatePythonArtifactInventory(backendRoot, sbom) {
  const approval = JSON.parse(readFileSync(
    resolve(projectRoot, 'config', 'pyinstaller-approved-distributions.json'),
    'utf8',
  ))
  assertExactKeys(
    approval,
    ['schema', 'platform', 'python_version', 'distributions'],
    'PyInstaller distribution 批准锁',
  )
  if (
    approval.schema !== 'netconsole.pyinstaller-approved-distributions.v1'
    || approval.platform !== 'windows-x64'
    || approval.python_version !== '3.13'
  ) {
    throw new Error('Electron 包 PyInstaller distribution 批准锁平台或版本不匹配。')
  }
  const approved = validatePythonDistributionRecords(
    approval.distributions,
    'PyInstaller distribution 批准锁',
  )

  const inventoryPath = resolve(
    backendRoot,
    '_internal',
    'netconsole',
    'assets',
    'pyinstaller-artifact-inventory.json',
  )
  const inventory = JSON.parse(readFileSync(inventoryPath, 'utf8'))
  assertExactKeys(
    inventory,
    ['schema', 'executable', 'distributions'],
    'PyInstaller 制品清单',
  )
  if (inventory.schema !== 'netconsole.pyinstaller-artifact-inventory.v1') {
    throw new Error('Electron 包 PyInstaller 制品清单 schema 不受支持。')
  }
  assertExactKeys(inventory.executable, ['name', 'sha256'], 'PyInstaller EXE 记录')
  const backendExecutable = resolve(backendRoot, 'NetConsoleBackend.exe')
  if (
    inventory.executable.name !== 'NetConsoleBackend.exe'
    || inventory.executable.sha256 !== sha256(backendExecutable)
  ) {
    throw new Error('Electron 包 PyInstaller EXE 与制品清单哈希不一致。')
  }
  const actual = validatePythonDistributionRecords(
    inventory.distributions,
    'PyInstaller 制品清单',
  )
  if (!isDeepStrictEqual([...actual], [...approved])) {
    throw new Error('Electron 包 PyInstaller 制品清单不匹配人工批准锁。')
  }

  const sbomPython = new Map()
  for (const item of sbom.components) {
    const match = /^pkg:pypi\/([^@?#]+)@([^?#]+)$/.exec(String(item.purl ?? ''))
    if (!match) continue
    const name = normalizePythonDistributionName(decodeURIComponent(match[1]))
    const version = decodeURIComponent(match[2])
    if (sbomPython.has(name)) throw new Error(`Electron 包 SBOM Python 组件重复：${name}`)
    sbomPython.set(name, version)
  }
  const sortedSbomPython = new Map(
    [...sbomPython].sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
  )
  if (!isDeepStrictEqual([...sortedSbomPython], [...actual])) {
    throw new Error('Electron 包 SBOM Python 组件与真实 PyInstaller 制品清单不一致。')
  }
}

function validatePythonDistributionRecords(records, label) {
  if (!Array.isArray(records)) throw new Error(`Electron 包 ${label}不是数组。`)
  const result = new Map()
  let previous = ''
  for (const record of records) {
    assertExactKeys(record, ['name', 'version'], `${label} distribution`)
    const name = String(record.name ?? '')
    const version = String(record.version ?? '')
    if (
      !name
      || name !== normalizePythonDistributionName(name)
      || !version
      || /[\\/:]/.test(version)
      || result.has(name)
      || (previous && previous >= name)
    ) {
      throw new Error(`Electron 包 ${label}包含无效、重复或未排序组件：${name || '<unknown>'}`)
    }
    result.set(name, version)
    previous = name
  }
  return result
}

function normalizePythonDistributionName(value) {
  return String(value).trim().toLowerCase().replace(/[-_.]+/g, '-')
}

function validateIperfDistribution(root = resolve(unpackedRoot, 'resources', 'backend', 'tools', 'windows-x64', 'iperf3')) {
  const provenance = JSON.parse(readFileSync(resolve(root, 'SOURCE_PROVENANCE.json'), 'utf8'))
  assertExactKeys(provenance, [
    'schema_version', 'component', 'version', 'platform', 'verified_at', 'distribution',
    'files', 'license_files', 'upstream_sources', 'compliance_files',
    'corresponding_source_notice', 'external_distribution_source_policy', 'distributor_license_file',
  ], 'iPerf3 provenance root')
  assertExactObject(provenance.distribution, {
    repository: 'https://github.com/ar51an/iperf3-win-builds',
    tag: '3.21',
    tag_commit: '7a24a0a352b6e177993e3b6375e7d38bc8f913e8',
    release_id: 307349802,
    release_url: 'https://github.com/ar51an/iperf3-win-builds/releases/tag/3.21',
    asset_name: 'iperf-3.21-win64-dynamic-auth.zip',
    asset_id: 392879715,
    asset_url: 'https://github.com/ar51an/iperf3-win-builds/releases/download/3.21/iperf-3.21-win64-dynamic-auth.zip',
    published_at: '2026-04-10T01:44:57Z',
    sha256: '0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb',
  }, 'iPerf3 distribution provenance')
  if (
    provenance.schema_version !== 'netconsole.tool-provenance.v1'
    || provenance.component !== 'iperf3-win64-dynamic-auth'
    || provenance.version !== '3.21'
    || provenance.platform !== 'windows-x64-cygwin'
    || provenance.verified_at !== '2026-07-18'
    || provenance.corresponding_source_notice !== 'CORRESPONDING_SOURCE.md'
    || provenance.external_distribution_source_policy !== 'publish the exact corresponding source archive beside the binary release or provide a valid written offer'
    || provenance.distributor_license_file !== 'licenses/AR51AN_APACHE-2.0.txt'
  ) {
    throw new Error('Electron 包 iPerf3 来源不是已批准的 3.21 dynamic-auth 资产。')
  }
  const declared = assertExactNamedEntries(provenance.files, expectedIperfFileEntries, 'iPerf3 文件来源清单')
  assertExactNamedEntries(provenance.upstream_sources, expectedIperfUpstreamSources, 'iPerf3 上游来源清单')
  for (const [name, expected] of Object.entries(expectedIperfFiles)) {
    const actual = createHash('sha256').update(readFileSync(resolve(root, name))).digest('hex')
    if (actual !== expected || declared.get(name).sha256 !== expected) {
      throw new Error(`Electron 包 iPerf3 文件哈希不匹配：${name}`)
    }
  }
  const declaredLicenses = assertExactNamedEntries(provenance.license_files, namedHashEntries(expectedIperfLicenseFiles), 'iPerf3 许可证来源清单')
  for (const [name, expected] of Object.entries(expectedIperfLicenseFiles)) {
    const actual = sha256(resolve(root, 'licenses', name))
    if (actual !== expected || declaredLicenses.get(name).sha256 !== expected) {
      throw new Error(`Electron 包 iPerf3 许可证哈希不匹配：${name}`)
    }
  }
  assertExactNamedEntries(provenance.compliance_files, namedHashEntries(expectedIperfComplianceFiles), 'iPerf3 对应源码清单')
  for (const [name, expected] of Object.entries(expectedIperfComplianceFiles)) {
    if (sha256(resolve(root, name)) !== expected) {
      throw new Error(`Electron 包 iPerf3 对应源码材料哈希不匹配：${name}`)
    }
  }
  validateAllowedFiles(root, allowedIperfFiles, 'iPerf3')
}

function validateFpingDistribution(root = resolve(unpackedRoot, 'resources', 'backend', 'tools', 'windows-x64', 'fping')) {
  const provenance = JSON.parse(readFileSync(resolve(root, 'SOURCE_PROVENANCE.json'), 'utf8'))
  assertExactKeys(provenance, [
    'schema_version', 'component', 'version', 'platform', 'verified_at', 'build', 'files',
    'license_files', 'compliance_files', 'upstream_sources', 'corresponding_source_notice',
    'external_distribution_source_policy',
  ], 'fping provenance root')
  assertExactObject(provenance.build, {
    method: 'local Cygwin x86_64 build',
    built_at: '2026-06-27T00:28:00+08:00',
    git_describe_at_build: 'v5.5-dirty',
    source_state: 'upstream v5.5 plus archived Cygwin ICMP compatibility patch',
    configure_args: ['--disable-ipv6', '--enable-safe-limits'],
    patch_file: 'CYGWIN_ICMP_COMPAT.patch',
    patch_sha256: expectedFpingComplianceFiles['CYGWIN_ICMP_COMPAT.patch'],
    recipe_file: 'BUILD_RECIPE.md',
    recipe_sha256: expectedFpingComplianceFiles['BUILD_RECIPE.md'],
    network_required_during_product_packaging: false,
  }, 'fping build provenance')
  if (
    provenance.schema_version !== 'netconsole.tool-provenance.v1'
    || provenance.component !== 'fping-windows-x64-cygwin'
    || provenance.version !== '5.5'
    || provenance.platform !== 'windows-x64-cygwin'
    || provenance.verified_at !== '2026-07-18'
    || provenance.corresponding_source_notice !== 'CORRESPONDING_SOURCE.md'
    || provenance.external_distribution_source_policy !== 'publish the exact corresponding source archive beside the binary release or provide a valid written offer'
  ) {
    throw new Error('Electron 包 fping 来源不是已批准的本地 Cygwin x64 构建。')
  }
  const declared = assertExactNamedEntries(provenance.files, expectedFpingFileEntries, 'fping 文件来源清单')
  for (const [name, expected] of Object.entries(expectedFpingFiles)) {
    if (sha256(resolve(root, name)) !== expected || declared.get(name).sha256 !== expected) {
      throw new Error(`Electron 包 fping 文件哈希不匹配：${name}`)
    }
  }
  const declaredLicenses = assertExactNamedEntries(provenance.license_files, namedHashEntries(expectedFpingLicenseFiles), 'fping 许可证来源清单')
  for (const [name, expected] of Object.entries(expectedFpingLicenseFiles)) {
    if (sha256(resolve(root, name)) !== expected || declaredLicenses.get(name).sha256 !== expected) {
      throw new Error(`Electron 包 fping 许可证哈希不匹配：${name}`)
    }
  }
  if (!readFileSync(resolve(root, 'CORRESPONDING_SOURCE.md'), 'utf8').trim()) {
    throw new Error('Electron 包 fping 缺少对应源码说明。')
  }
  const declaredCompliance = assertExactNamedEntries(provenance.compliance_files, namedHashEntries(expectedFpingComplianceFiles), 'fping 对应源码清单')
  for (const [name, expected] of Object.entries(expectedFpingComplianceFiles)) {
    if (sha256(resolve(root, name)) !== expected || declaredCompliance.get(name).sha256 !== expected) {
      throw new Error(`Electron 包 fping 对应源码材料哈希不匹配：${name}`)
    }
  }
  assertExactNamedEntries(provenance.upstream_sources, expectedFpingUpstreamSources, 'fping 上游来源清单')
  validateAllowedFiles(root, allowedFpingFiles, 'fping')
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function namedHashEntries(expected) {
  return Object.fromEntries(Object.entries(expected).map(([name, sha256]) => [name, { name, sha256 }]))
}

function assertExactKeys(actual, expected, label) {
  if (!actual || typeof actual !== 'object' || Array.isArray(actual)) {
    throw new Error(`Electron 包 ${label}不是对象。`)
  }
  const actualKeys = Object.keys(actual)
  if (actualKeys.length !== expected.length || expected.some((name) => !Object.hasOwn(actual, name))) {
    throw new Error(`Electron 包 ${label}属性不是精确批准集合。`)
  }
}

function assertExactObject(actual, expected, label) {
  if (!isDeepStrictEqual(actual, expected)) {
    throw new Error(`Electron 包 ${label}不匹配批准清单。`)
  }
}

function assertExactNamedEntries(actual, expected, label) {
  if (!Array.isArray(actual) || actual.length !== Object.keys(expected).length) {
    throw new Error(`Electron 包 ${label}不是精确批准集合。`)
  }
  const entries = new Map()
  for (const item of actual) {
    const name = item && typeof item === 'object' ? item.name : undefined
    if (typeof name !== 'string' || !name || entries.has(name)) {
      throw new Error(`Electron 包 ${label}包含缺失或重复名称。`)
    }
    entries.set(name, item)
  }
  for (const [name, expectedItem] of Object.entries(expected)) {
    if (!entries.has(name) || !isDeepStrictEqual(entries.get(name), expectedItem)) {
      throw new Error(`Electron 包 ${label}条目不匹配：${name}`)
    }
  }
  return entries
}

function validateAllowedFiles(root, allowed, label) {
  const actual = new Set(listRelativeFiles(root))
  const unexpected = [...actual].filter((path) => !allowed.has(path))
  const missing = [...allowed].filter((path) => !actual.has(path))
  if (unexpected.length || missing.length) {
    throw new Error(`Electron 包 ${label} 目录不是精确批准集合；未批准：${unexpected.join(', ') || '<none>'}；缺失：${missing.join(', ') || '<none>'}`)
  }
}

function listRelativeFiles(root, current = root) {
  const result = []
  for (const entry of readdirSync(current, { withFileTypes: true })) {
    const path = resolve(current, entry.name)
    if (entry.isDirectory()) result.push(...listRelativeFiles(root, path))
    else if (entry.isFile()) result.push(relative(root, path).replaceAll('\\', '/'))
  }
  return result
}

function readElectronRuntimeVersions() {
  const result = spawnSync(
    executable,
    ['-p', 'JSON.stringify(process.versions)'],
    {
      cwd: unpackedRoot,
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
      encoding: 'utf8',
      timeout: 15_000,
      windowsHide: true,
    },
  )
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`无法读取 Electron runtime 版本，exit=${result.status}`)
  const versions = JSON.parse(String(result.stdout ?? '').trim())
  for (const key of ['electron', 'chrome', 'node']) {
    if (!String(versions[key] ?? '').trim()) throw new Error(`Electron runtime 缺少 ${key} 版本。`)
  }
  return versions
}

function validateRuntimeVersion(items, name, expected) {
  const item = items.find((entry) => String(entry.name).toLowerCase() === name.toLowerCase())
  if (!item || String(item.version) !== String(expected)) {
    throw new Error(`${name} 版本与 Electron runtime 不一致：expected=${expected}, actual=${item?.version ?? '<missing>'}`)
  }
}

function validatePurl(value) {
  if (!value || /\s/.test(value)) return 'PURL 缺失或含空白'
  return /^pkg:(?:pypi|npm|generic)\/[^@?#]+@[^?#]+$/.test(value) ? '' : 'PURL 格式无效'
}

function validateDeviceCommandProfiles() {
  const path = resolve(
    unpackedRoot,
    'resources',
    'backend',
    '_internal',
    'netconsole',
    'assets',
    'device_command_profiles.json',
  )
  const payload = JSON.parse(readFileSync(path, 'utf8'))
  if (payload.schema_version !== '2026.07.device-command-profiles.v1') {
    throw new Error('Electron 包命令 Profile schema_version 不受支持。')
  }
  if (!Array.isArray(payload.profiles) || !payload.profiles.length) {
    throw new Error('Electron 包命令 Profile 不能为空。')
  }
  const operations = new Set(payload.profiles.map((profile) => profile.operation_id))
  if (operations.size !== 1 || !operations.has('device.inventory.collect')) {
    throw new Error('Electron 包命令 Profile 只能包含 device.inventory.collect。')
  }
  const profileIds = new Set(payload.profiles.map((profile) => profile.profile_id))
  if (
    profileIds.size !== payload.profiles.length
    || profileIds.size !== expectedDeviceInventoryProfiles.size
    || [...expectedDeviceInventoryProfiles.keys()].some((profileId) => !profileIds.has(profileId))
  ) {
    throw new Error('Electron 包命令 Profile 白名单不匹配。')
  }
  for (const profile of payload.profiles) {
    const expectedCommands = expectedDeviceInventoryProfiles.get(profile.profile_id)
    if (!expectedCommands) {
      throw new Error(`Electron 包命令 Profile 不在白名单内：${profile.profile_id ?? '<unknown>'}`)
    }
    const commands = Array.isArray(profile.steps) ? profile.steps.map((step) => step.command) : []
    if (!isDeepStrictEqual(commands, expectedCommands)) {
      throw new Error(`Electron 包命令 Profile 命令序列不匹配：${profile.profile_id ?? '<unknown>'}`)
    }
  }
}

function isQtResidue(path) {
  const normalized = path.toLowerCase().replaceAll('\\', '/')
  const parts = normalized.split('/').filter(Boolean)
  if (parts.some((part) => {
    const canonical = part.replaceAll('_', '-').replaceAll('.', '-')
    return qtPackagePrefixes.some((prefix) => canonical === prefix || canonical.startsWith(`${prefix}-`))
  })) return true
  const basename = parts.at(-1) ?? ''
  return qtBasenames.has(basename)
    || qtLibraryPattern.test(basename)
    || qtPythonExtensionPattern.test(basename)
    || qtTranslationPattern.test(basename)
}

function walk(root) {
  const result = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = resolve(root, entry.name)
    result.push(path)
    if (entry.isDirectory()) result.push(...walk(path))
  }
  return result
}
