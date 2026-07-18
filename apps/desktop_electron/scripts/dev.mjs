import { spawn, execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { createServer } from 'node:net'
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

async function assertDevPortAvailable() {
  await new Promise((resolvePromise, reject) => {
    const probe = createServer()
    probe.once('error', () => reject(new Error(`Vite dev port ${devPort} is already in use`)))
    probe.listen(devPort, '127.0.0.1', () => {
      probe.close((cause) => cause ? reject(cause) : resolvePromise())
    })
  })
}

await runNode([typescriptCli, '--noEmit', '-p', resolve(appRoot, 'tsconfig.json')], 'Electron typecheck')
await runNode([buildScript], 'Electron main/preload build')
await assertDevPortAvailable()

const vite = spawnNode([
  viteCli,
  '--host',
  '127.0.0.1',
  '--port',
  String(devPort),
  '--strictPort',
], { cwd: webRoot })

let electron
let stopping = false

function stopChildren() {
  if (stopping) return
  stopping = true
  electron?.kill()
  vite.kill()
}

process.once('SIGINT', stopChildren)
process.once('SIGTERM', stopChildren)

try {
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
      NETCONSOLE_PROJECT_ROOT: projectRoot,
      ...(pythonExecutable ? { NETCONSOLE_PYTHON: pythonExecutable } : {}),
      ...(smoke ? { NETCONSOLE_ELECTRON_SMOKE_TEST: '1' } : {}),
    },
  })
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
  stopChildren()
}
