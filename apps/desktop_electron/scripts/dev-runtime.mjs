import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { basename, join, resolve, sep } from 'node:path'
import { tmpdir } from 'node:os'

const ISOLATED_PREFIX = 'NetConsole-Codex-'

export function discoverProjectPython({ projectRoot, commonRoot, environment = process.env, platform = process.platform, probe = true, log = () => undefined }) {
  log('ELECTRON_PYTHON_DISCOVERY_START')
  const relative = platform === 'win32' ? ['.venv', 'Scripts', 'python.exe'] : ['.venv', 'bin', 'python']
  const candidates = [
    ...(environment.NETCONSOLE_PYTHON ? [{ path: resolve(environment.NETCONSOLE_PYTHON), source: 'environment' }] : []),
    { path: resolve(projectRoot, ...relative), source: 'checkout' },
    ...(commonRoot && resolve(commonRoot) !== resolve(projectRoot)
      ? [{ path: resolve(commonRoot, ...relative), source: 'common-worktree' }]
      : []),
  ]
  const selected = candidates.find((candidate) => existsSync(candidate.path))
  if (!selected) {
    log('ELECTRON_PYTHON_DISCOVERY_FAILED')
    throw new Error(`未找到项目 Python 运行时；已检查：${candidates.map((item) => item.source).join('、')}`)
  }
  if (probe) {
    try {
      execFileSync(selected.path, ['--version'], { stdio: 'ignore', windowsHide: true })
    } catch {
      log('ELECTRON_PYTHON_DISCOVERY_FAILED')
      throw new Error(`项目 Python 无法执行（来源：${selected.source}），请修复虚拟环境后重试`)
    }
  }
  log('ELECTRON_PYTHON_DISCOVERY_SELECTED', selected.source)
  return selected.path
}

export function createIsolatedRuntime(systemTempRoot = tmpdir()) {
  const root = mkdtempSync(join(resolve(systemTempRoot), ISOLATED_PREFIX))
  const runtime = {
    root,
    dataRoot: resolve(root, 'data'),
    runtimeRoot: resolve(root, 'runtime'),
    userDataRoot: resolve(root, 'electron-user-data'),
  }
  for (const path of [runtime.dataRoot, runtime.runtimeRoot, runtime.userDataRoot]) mkdirSync(path, { recursive: true })
  return runtime
}

export function cleanupIsolatedRuntime(root, systemTempRoot = tmpdir()) {
  const target = resolve(root)
  const tempRoot = resolve(systemTempRoot)
  if (!target.startsWith(`${tempRoot}${sep}`) || !basename(target).startsWith(ISOLATED_PREFIX)) {
    throw new Error('Refusing to clean an unexpected isolated runtime directory')
  }
  rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
}
