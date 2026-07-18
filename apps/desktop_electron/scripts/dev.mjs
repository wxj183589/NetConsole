import { spawn, execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { createRequire } from 'node:module'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { basename, dirname, join, resolve, sep } from 'node:path'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const webRoot = resolve(projectRoot, 'apps', 'web')
const webRequire = createRequire(resolve(webRoot, 'package.json'))
const viteCli = resolve(dirname(webRequire.resolve('vite/package.json')), 'bin', 'vite.js')
const typescriptCli = resolve(dirname(require.resolve('typescript/package.json')), 'bin', 'tsc')
const buildScript = resolve(appRoot, 'scripts', 'build.mjs')
const devPort = 5173
const devUrl = `http://127.0.0.1:${devPort}`
const smoke = process.argv.includes('--smoke') || process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1'
const codex = process.argv.includes('--codex')
const codexBackendPort = 8000
const codexBackendUrl = `http://127.0.0.1:${codexBackendPort}`
const codexSessionToken = codex ? randomBytes(32).toString('base64url') : ''
let codexDataRoot = ''

function spawnNode(args, options = {}) {
  return spawn(process.execPath, args, {
    cwd: appRoot,
    stdio: 'inherit',
    shell: false,
    ...options,
  })
}

function runNode(args, label) {
  return new Promise((resolvePromise, reject) => {
    const child = spawnNode(args)
    child.once('error', reject)
    child.once('exit', (code) => {
      if (code === 0) resolvePromise()
      else reject(new Error(`${label} failed with exit code ${code}`))
    })
  })
}

function discoverPython() {
  if (process.env.NETCONSOLE_PYTHON) return process.env.NETCONSOLE_PYTHON
  const roots = [projectRoot]
  try {
    const commonGitDir = execFileSync(
      'git',
      ['-C', projectRoot, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' },
    ).trim()
    roots.push(resolve(commonGitDir, '..'))
  } catch {
    // 普通 checkout 下 projectRoot 已足够；后续由主进程给出明确缺失错误。
  }
  const relative = process.platform === 'win32' ? ['.venv', 'Scripts', 'python.exe'] : ['.venv', 'bin', 'python']
  return roots.map((root) => resolve(root, ...relative)).find(existsSync)
}

async function waitForVite(vite, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (vite.exitCode !== null || vite.signalCode !== null) {
      throw new Error('Vite exited before becoming ready')
    }
    try {
      const response = await fetch(`${devUrl}/@vite/client`)
      if (response.ok && (await response.text()).includes('vite')) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
        if (vite.exitCode === null && vite.signalCode === null) return
        throw new Error('Vite exited before becoming ready')
      }
    } catch {
      // Vite 尚未监听。
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
  }
  throw new Error(`Vite did not become ready at ${devUrl}`)
}

async function assertPortAvailable(port, label) {
  await new Promise((resolvePromise, reject) => {
    const probe = createServer()
    probe.once('error', () => reject(new Error(`${label} port ${port} is already in use`)))
    probe.listen(port, '127.0.0.1', () => {
      probe.close((cause) => cause ? reject(cause) : resolvePromise())
    })
  })
}

async function waitForCodexBackend(electronProcess, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (electronProcess.exitCode !== null || electronProcess.signalCode !== null) {
      throw new Error('Electron exited before the Codex development backend became ready')
    }
    try {
      const response = await fetch(`${codexBackendUrl}/api/dev/runtime-status`, {
        cache: 'no-store',
        headers: { 'X-NetConsole-Session': codexSessionToken },
      })
      if (response.ok) {
        const status = await response.json()
        if (
          status.runtime_mode === 'electron-development'
          && status.backend_ready === true
          && status.agent_controller_ready === true
          && status.traffic_supervisor_ready === true
          && status.data_root === '<redacted>'
        ) return status
      }
    } catch {
      // Electron 仍在启动受管 Backend。
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
  }
  throw new Error('Codex development backend did not become ready')
}

function cleanupCodexDataRoot() {
  if (!codexDataRoot) return
  const resolvedTemp = resolve(tmpdir())
  const resolvedData = resolve(codexDataRoot)
  if (!resolvedData.startsWith(`${resolvedTemp}${sep}`) || !basename(resolvedData).startsWith('NetConsole-Codex-')) {
    throw new Error('Refusing to clean an unexpected Codex data directory')
  }
  rmSync(resolvedData, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
}

await runNode([typescriptCli, '--noEmit', '-p', resolve(appRoot, 'tsconfig.json')], 'Electron typecheck')
await runNode([buildScript], 'Electron main/preload build')
await assertPortAvailable(devPort, 'Vite dev')
if (codex) await assertPortAvailable(codexBackendPort, 'Codex backend')

let vite
let electron
let stoppingPromise

function waitForChildExit(child, timeoutMs = 5_000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true)
  return new Promise((resolvePromise) => {
    let settled = false
    const finish = (exited) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      child.removeListener('exit', onExit)
      child.removeListener('close', onExit)
      child.removeListener('error', onExit)
      resolvePromise(exited)
    }
    const onExit = () => finish(true)
    const timer = setTimeout(() => finish(false), timeoutMs)
    child.once('exit', onExit)
    child.once('close', onExit)
    child.once('error', onExit)
  })
}

function terminateProcessTree(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  if (process.platform === 'win32' && child.pid) {
    try {
      execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true,
      })
      return
    } catch {
      // 进程可能已自行退出；下面的普通 kill 负责最后确认。
    }
  }
  child.kill('SIGTERM')
}

function stopChildren() {
  if (stoppingPromise) return stoppingPromise
  stoppingPromise = (async () => {
    const children = [electron, vite].filter(Boolean)
    for (const child of children) terminateProcessTree(child)
    const exited = await Promise.all(children.map((child) => waitForChildExit(child)))
    for (const [index, child] of children.entries()) {
      if (!exited[index] && child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    }
    await Promise.all(children.map((child) => waitForChildExit(child, 1_000)))
  })()
  return stoppingPromise
}

function requestGracefulSignalShutdown() {
  void (async () => {
    const exited = await waitForChildExit(electron, 5_000)
    if (!exited) await stopChildren()
  })()
}

process.once('SIGINT', requestGracefulSignalShutdown)
process.once('SIGTERM', requestGracefulSignalShutdown)

try {
  if (codex) codexDataRoot = mkdtempSync(join(tmpdir(), 'NetConsole-Codex-'))
  vite = spawnNode([
    viteCli,
    '--host',
    '127.0.0.1',
    '--port',
    String(devPort),
    '--strictPort',
  ], {
    cwd: webRoot,
    env: {
      ...process.env,
      ...(codex ? {
        VITE_API_BASE: codexBackendUrl,
        VITE_DEV_SESSION_TOKEN: codexSessionToken,
      } : {}),
    },
  })
  await waitForVite(vite)
  const electronExecutable = require('electron')
  const pythonExecutable = discoverPython()
  const electronEnv = { ...process.env }
  delete electronEnv.ELECTRON_RUN_AS_NODE
  electron = spawn(electronExecutable, [appRoot], {
    cwd: projectRoot,
    stdio: 'inherit',
    shell: false,
    env: {
      ...electronEnv,
      NETCONSOLE_WEB_DEV_URL: devUrl,
      NETCONSOLE_DEV_MODE: '1',
      NETCONSOLE_PROJECT_ROOT: projectRoot,
      ...(pythonExecutable ? { NETCONSOLE_PYTHON: pythonExecutable } : {}),
      ...(codex ? {
        NETCONSOLE_DATA_ROOT: codexDataRoot,
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DEV_BACKEND_PORT: String(codexBackendPort),
        NETCONSOLE_DEV_SESSION_TOKEN: codexSessionToken,
      } : {}),
      ...(smoke ? { NETCONSOLE_ELECTRON_SMOKE_TEST: '1' } : {}),
    },
  })
  if (codex) {
    const status = await waitForCodexBackend(electron)
    process.stdout.write(`NetConsole Codex development runtime ready: ${devUrl}\n`)
    process.stdout.write(`Runtime mode: ${String(status.runtime_mode || 'electron-development')}\n`)
    process.stdout.write('Vue tests: pnpm --dir apps/web test\n')
    process.stdout.write('Electron tests: pnpm --dir apps/desktop_electron test\n')
  }
  const exitCode = await new Promise((resolvePromise, reject) => {
    let settled = false
    const finish = (code) => {
      if (settled) return
      settled = true
      resolvePromise(code ?? 1)
    }
    electron.once('error', reject)
    electron.once('exit', finish)
    electron.once('close', finish)
  })
  process.exitCode = exitCode
} finally {
  await stopChildren()
  if (codex) {
    try {
      cleanupCodexDataRoot()
    } catch {
      process.stderr.write('Codex temporary data cleanup failed\n')
    }
  }
}
