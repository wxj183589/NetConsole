import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const selection = String(process.argv[2] || 'both').trim().toLowerCase()
const python = discoverPython()

if (!['full', 'customer', 'both'].includes(selection)) {
  throw new Error(`版本选择仅允许 full/customer/both，当前为：${selection}`)
}
if (!python) throw new Error('未找到项目 .venv Python，无法构建版本安装包')

execFileSync(
  python,
  ['-m', 'scripts.build.build_edition_installers', '--editions', selection],
  { cwd: projectRoot, env: { ...process.env }, stdio: 'inherit' },
)

function discoverPython() {
  if (process.env.NETCONSOLE_PYTHON) return process.env.NETCONSOLE_PYTHON
  const relative = process.platform === 'win32'
    ? ['.venv', 'Scripts', 'python.exe']
    : ['.venv', 'bin', 'python']
  const candidate = resolve(projectRoot, ...relative)
  return existsSync(candidate) ? candidate : undefined
}
