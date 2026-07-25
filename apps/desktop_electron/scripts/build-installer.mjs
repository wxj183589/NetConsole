import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const python = process.env.NETCONSOLE_PYTHON || resolve(
  projectRoot,
  '.venv',
  process.platform === 'win32' ? 'Scripts' : 'bin',
  process.platform === 'win32' ? 'python.exe' : 'python',
)

if (!existsSync(python)) {
  throw new Error(`未找到项目 .venv Python：${python}`)
}

execFileSync(
  python,
  ['-m', 'scripts.build.build_installer'],
  { cwd: projectRoot, env: process.env, stdio: 'inherit' },
)
