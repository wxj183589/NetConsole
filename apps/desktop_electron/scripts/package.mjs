import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, readFileSync, rmSync } from 'node:fs'
import { dirname, delimiter, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))
const version = String(packageJson.version)
const python = discoverPython()
const releaseRoot = resolve(projectRoot, 'dist', `v${version}`, 'pyinstaller', 'NetConsoleBackend')
const stagingRoot = resolve(appRoot, 'dist', 'package-resources')
const backendStaging = resolve(stagingRoot, 'backend')

if (!python) throw new Error('未找到项目 .venv Python，无法构建 NetConsoleBackend.exe')

const env = { ...process.env }
const sourceRoot = resolve(projectRoot, 'src')
env.PYTHONPATH = env.PYTHONPATH ? `${sourceRoot}${delimiter}${env.PYTHONPATH}` : sourceRoot

execFileSync(
  python,
  [
    '-m',
    'scripts.build.build_release',
    '--backend',
    'pyinstaller',
    '--skip-install',
    '--no-zip',
  ],
  { cwd: projectRoot, env, stdio: 'inherit' },
)

if (!existsSync(resolve(releaseRoot, 'NetConsoleBackend.exe'))) {
  throw new Error(`Backend 构建产物不存在：${releaseRoot}`)
}

rmSync(stagingRoot, { recursive: true, force: true })
cpSync(releaseRoot, backendStaging, { recursive: true, force: false })
console.log(`Electron Backend staged: ${backendStaging}`)

function discoverPython() {
  if (process.env.NETCONSOLE_PYTHON) return process.env.NETCONSOLE_PYTHON
  const relative = process.platform === 'win32'
    ? ['.venv', 'Scripts', 'python.exe']
    : ['.venv', 'bin', 'python']
  const candidate = resolve(projectRoot, ...relative)
  return existsSync(candidate) ? candidate : undefined
}
