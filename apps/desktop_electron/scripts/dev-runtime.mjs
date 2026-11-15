import { execFileSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, mkdtempSync, realpathSync, rmSync } from 'node:fs'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'

const repositoryRoot = resolve(import.meta.dirname, '..', '..', '..')
const repositoryParent = resolve(repositoryRoot, '..')
const workspaceRoot = basename(repositoryParent).toLowerCase() === 'worktrees'
  && basename(resolve(repositoryParent, '..')).toLowerCase() === 'netconsole-workspace'
  && existsSync(resolve(repositoryParent, '..', 'NetConsole', '.git'))
  ? resolve(repositoryParent, '..')
  : repositoryParent
const WINDOWS_TEST_DATA_ROOT = resolve(workspaceRoot, 'test-data', 'NetConsole')
const FORBIDDEN_PERSISTENT_ROOTS = [
  'D:\\NetConsoleData',
  'D:\\NetConsoleData-dev',
  'G:\\NetConsoleData',
]

export function resolveDevelopmentIsolation({
  codex = false,
  smoke = false,
  taskCenterSmoke = false,
  workspaceTraySmoke = false,
  explicitRoot = '',
} = {}) {
  return Boolean(codex || smoke || taskCenterSmoke || workspaceTraySmoke || explicitRoot)
}

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

export function createIsolatedRuntime(testDataRoot = WINDOWS_TEST_DATA_ROOT, explicitRoot = '') {
  const base = resolve(testDataRoot)
  mkdirSync(base, { recursive: true })
  const root = explicitRoot ? validateIsolatedRoot(explicitRoot, base) : mkdtempSync(join(base, 'electron-'))
  if (explicitRoot) mkdirSync(root, { recursive: true })
  const runtime = {
    root,
    dataRoot: root,
    runtimeRoot: resolve(root, 'runtime'),
    userDataRoot: resolve(root, 'runtime', 'electron', 'user-data'),
  }
  for (const path of [runtime.dataRoot, runtime.runtimeRoot, runtime.userDataRoot]) mkdirSync(path, { recursive: true })
  return runtime
}

export function cleanupIsolatedRuntime(root, testDataRoot = WINDOWS_TEST_DATA_ROOT) {
  const target = validateIsolatedRoot(root, resolve(testDataRoot))
  rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
}

function validateIsolatedRoot(value, base) {
  const target = resolve(value)
  if (!isPathWithin(target, base)) {
    throw new Error('Refusing to use an unexpected isolated runtime directory')
  }
  const realBase = safeRealPath(base)
  const realTarget = safeRealPath(target)
  if (!isPathWithin(realTarget, realBase) || isForbiddenPersistentRoot(realTarget)) {
    throw new Error('Refusing to use an isolated runtime redirected outside the test-data root')
  }
  if (existsSync(target) && lstatSync(target).isSymbolicLink()) {
    throw new Error('Refusing to use a symbolic-link isolated runtime directory')
  }
  return target
}

function safeRealPath(value) {
  let cursor = resolve(value)
  const missing = []
  while (!existsSync(cursor)) {
    const parent = dirname(cursor)
    if (parent === cursor) return resolve(value)
    missing.unshift(basename(cursor))
    cursor = parent
  }
  return resolve(realpathSync.native(cursor), ...missing)
}

function isPathWithin(candidate, parent) {
  const child = relative(parent, candidate)
  return child !== '' && child !== '..' && !child.startsWith(`..${sep}`) && !isAbsolute(child)
}

function isForbiddenPersistentRoot(value) {
  return FORBIDDEN_PERSISTENT_ROOTS.some((root) => {
    const normalized = resolve(root)
    return value === normalized || isPathWithin(value, normalized)
  })
}
