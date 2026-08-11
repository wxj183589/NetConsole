import { spawn, execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'

import { cleanupIsolatedRuntime, createIsolatedRuntime, discoverProjectPython } from './dev-runtime.mjs'

const require = createRequire(import.meta.url)
const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const rendererRoot = resolve(projectRoot, 'apps', 'desktop_renderer')
const rendererRequire = createRequire(resolve(rendererRoot, 'package.json'))
const viteCli = resolve(dirname(rendererRequire.resolve('vite/package.json')), 'bin', 'vite.js')
const typescriptCli = resolve(dirname(require.resolve('typescript/package.json')), 'bin', 'tsc')
const buildScript = resolve(appRoot, 'scripts', 'build.mjs')
const devPort = Number.parseInt(process.env.NETCONSOLE_DEV_PORT || '5173', 10)
if (!Number.isInteger(devPort) || devPort < 1 || devPort > 65_535) throw new Error('NETCONSOLE_DEV_PORT must be a valid TCP port')
const devUrl = `http://127.0.0.1:${devPort}`
const smoke = process.argv.includes('--smoke') || process.env.NETCONSOLE_ELECTRON_SMOKE_TEST === '1'
const taskCenterSmoke = process.argv.includes('--task-center') || process.argv.includes('--task-window')
const workspaceTraySmoke = process.argv.includes('--workspace-tray')
const codex = process.argv.includes('--codex')
const isolatedDataArgument = process.argv.indexOf('--isolated-test-data')
const explicitIsolatedDataRoot = isolatedDataArgument >= 0
  ? process.argv[isolatedDataArgument + 1]
  : ''
if (isolatedDataArgument >= 0 && !explicitIsolatedDataRoot) {
  throw new Error('--isolated-test-data requires an absolute D:\\NetConsoleTestData\\<run-id> path')
}
const isolated = smoke || taskCenterSmoke || workspaceTraySmoke || Boolean(explicitIsolatedDataRoot)
const codexBackendPort = 8000
const codexBackendUrl = `http://127.0.0.1:${codexBackendPort}`
const codexSessionToken = codex ? randomBytes(32).toString('base64url') : ''
let isolatedRuntime

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

function commonWorktreeRoot() {
  try {
    const commonGitDir = execFileSync(
      'git',
      ['-C', projectRoot, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' },
    ).trim()
    return resolve(commonGitDir, '..')
  } catch {
    return projectRoot
  }
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

async function warmTaskCenterModules() {
  const modules = [
    '/src/App.vue',
    '/src/task-center/components/GlobalTaskCenter.vue',
    '/src/views/job-center/JobCenterView.vue',
    '/src/components/NcStatusTag.vue',
    '/src/components/feedback/NcConfirmDialog.vue',
    '/src/components/table/NcColumnSettings.vue',
    '/src/components/table/NcDataTable.vue',
  ]
  for (let pass = 0; pass < 2; pass += 1) {
    for (const path of modules) {
      const response = await fetch(`${devUrl}${path}`, { cache: 'no-store' })
      if (!response.ok) throw new Error(`Task window module warmup failed: ${path}`)
      await response.text()
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 600))
  }
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

await runNode([typescriptCli, '--noEmit', '-p', resolve(appRoot, 'tsconfig.json')], 'Electron typecheck')
await runNode([buildScript], 'Electron main/preload build')
const pythonExecutable = discoverProjectPython({
  projectRoot,
  commonRoot: commonWorktreeRoot(),
  log: (event, detail = '') => process.stdout.write(`${event}${detail ? ` source=${detail}` : ''}\n`),
})
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
  if (isolated) isolatedRuntime = createIsolatedRuntime(undefined, explicitIsolatedDataRoot)
  process.stdout.write(isolated
    ? 'Isolated temporary test runtime - all data will be deleted\n'
    : 'Persistent development runtime\n')
  vite = spawnNode([
    viteCli,
    '--host',
    '127.0.0.1',
    '--port',
    String(devPort),
    '--strictPort',
  ], {
    cwd: rendererRoot,
    env: {
      ...process.env,
      ...(codex ? {
        VITE_API_BASE: codexBackendUrl,
        VITE_DEV_SESSION_TOKEN: codexSessionToken,
      } : {}),
    },
  })
  await waitForVite(vite)
  if (taskCenterSmoke) await warmTaskCenterModules()
  const electronExecutable = require('electron')
  const electronEnv = { ...process.env }
  delete electronEnv.ELECTRON_RUN_AS_NODE
  delete electronEnv.NETCONSOLE_DEV_TEMP_DATA_ROOT
  delete electronEnv.NETCONSOLE_DEV_TEMP_USER_DATA_ROOT
  delete electronEnv.NETCONSOLE_STORAGE_MODE
  electron = spawn(electronExecutable, [appRoot], {
    cwd: projectRoot,
    stdio: 'inherit',
    shell: false,
    env: {
      ...electronEnv,
      NETCONSOLE_RENDERER_DEV_URL: devUrl,
      NETCONSOLE_DEV_MODE: '1',
      NETCONSOLE_PROJECT_ROOT: projectRoot,
      NETCONSOLE_PYTHON: pythonExecutable,
      NETCONSOLE_STORAGE_MODE: isolated ? 'isolated_test' : 'persistent',
      NETCONSOLE_RUNTIME_MODE: isolated ? 'test' : 'desktop-development',
      ...(isolated ? {
        NETCONSOLE_DATA_ROOT: isolatedRuntime.dataRoot,
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        ...(taskCenterSmoke || workspaceTraySmoke ? { NETCONSOLE_ISOLATED_SMOKE: '1' } : {}),
        ...(codex ? {
        NETCONSOLE_DEV_BACKEND_PORT: String(codexBackendPort),
        NETCONSOLE_DEV_SESSION_TOKEN: codexSessionToken,
        } : {}),
      } : {}),
      ...(smoke ? { NETCONSOLE_ELECTRON_SMOKE_TEST: '1' } : {}),
      ...(taskCenterSmoke ? { NETCONSOLE_ELECTRON_TASK_CENTER_SMOKE: '1' } : {}),
      ...(workspaceTraySmoke ? { NETCONSOLE_ELECTRON_WORKSPACE_TRAY_SMOKE: '1' } : {}),
    },
  })
  if (codex) {
    const status = await waitForCodexBackend(electron)
    process.stdout.write(`NetConsole Codex development runtime ready: ${devUrl}\n`)
    process.stdout.write(`Runtime mode: ${String(status.runtime_mode || 'electron-development')}\n`)
    process.stdout.write('Vue tests: pnpm --dir apps/desktop_renderer test\n')
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
  if (isolatedRuntime) {
    try {
      cleanupIsolatedRuntime(isolatedRuntime.root)
    } catch {
      process.stderr.write('Isolated temporary runtime cleanup failed\n')
    }
  }
}
