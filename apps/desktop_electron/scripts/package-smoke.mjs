import { spawnSync } from 'node:child_process'
import { mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

const appRoot = resolve(import.meta.dirname, '..')
const projectRoot = resolve(appRoot, '..', '..')
const unpackedRoot = resolve(projectRoot, 'dist', 'electron', 'win-unpacked')
const executable = resolve(unpackedRoot, 'NetConsole.exe')
const forbiddenMarkers = [
  'pyside6',
  'shiboken6',
  'qfluentwidgets',
  'qt6core',
  'qt6gui',
  'qt6widgets',
  'qt6webengine',
  'qwindows.dll',
]

const residue = walk(unpackedRoot).filter((path) => {
  const lowered = path.toLowerCase().replaceAll('\\', '/')
  return forbiddenMarkers.some((marker) => lowered.includes(marker))
})
if (residue.length) throw new Error(`Electron 包检测到 Qt 残留：${residue.slice(0, 20).join(', ')}`)

const smokeRoot = mkdtempSync(join(tmpdir(), 'netconsole-electron-package-smoke-'))
try {
  const result = spawnSync(
    executable,
    [`--user-data-dir=${resolve(smokeRoot, 'electron')}`],
    {
      cwd: unpackedRoot,
      env: {
        ...process.env,
        NETCONSOLE_DATA_ROOT: resolve(smokeRoot, 'data-root'),
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

console.log('Electron packaged smoke passed without Qt runtime residue.')

function walk(root) {
  const result = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = resolve(root, entry.name)
    result.push(path)
    if (entry.isDirectory()) result.push(...walk(path))
  }
  return result
}
