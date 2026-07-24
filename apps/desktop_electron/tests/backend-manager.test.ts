import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'

import { describe, expect, it, vi } from 'vitest'

import {
  PythonBackendManager,
  type ManagedChildProcess,
  type SpawnProcess,
} from '../src/main/backend-manager'
import { DESKTOP_SESSION_HEADER } from '../src/shared/bridge'

const TOKEN = 'electron-test-token-abcdefghijklmnopqrstuvwxyz'

class FakeChild extends EventEmitter implements ManagedChildProcess {
  readonly stdin = new PassThrough()
  readonly stdout = new PassThrough()
  readonly stderr = new PassThrough()
  exitCode: number | null = null
  readonly signals: Array<NodeJS.Signals | number | undefined> = []

  constructor(
    respondToShutdown = true,
    private readonly respondToKill = true,
  ) {
    super()
    if (respondToShutdown) {
      this.stdin.on('data', (chunk) => {
        if (chunk.toString('utf8').includes('"command":"shutdown"')) {
          this.stdout.write('{"event":"netconsole.electron_backend.shutdown_ack"}\n')
          queueMicrotask(() => this.exit(0))
        }
      })
    }
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.signals.push(signal)
    if (!this.respondToKill) return false
    queueMicrotask(() => this.exit(0, typeof signal === 'string' ? signal : null))
    return true
  }

  announce(port = 43123): void {
    this.stdout.write(`${JSON.stringify({
      event: 'netconsole.electron_backend.listening',
      host: '127.0.0.1',
      port,
    })}\n`)
  }

  exit(code: number | null, signal: NodeJS.Signals | null = null): void {
    this.exitCode = code
    this.emit('exit', code, signal)
    this.stdout.end()
    this.stderr.end()
  }
}

function createManager(options: {
  child?: FakeChild
  fetchImpl?: typeof fetch
  logger?: (event: string, detail?: string) => void
  awaitProcessExit?: boolean
  environment?: NodeJS.ProcessEnv
  runtimeMode?: 'desktop-development' | 'desktop-packaged'
  announcedPort?: number
} = {}) {
  const child = options.child ?? new FakeChild()
  const spawnCalls: Array<{ command: string; args: string[]; options: Record<string, unknown> }> = []
  const spawnProcess: SpawnProcess = (command, args, spawnOptions) => {
    spawnCalls.push({ command, args, options: spawnOptions as Record<string, unknown> })
    const developmentPort = options.runtimeMode !== 'desktop-packaged'
      && options.environment?.NETCONSOLE_DEV_MODE === '1'
      ? Number(options.environment.NETCONSOLE_DEV_BACKEND_PORT || 0)
      : 0
    queueMicrotask(() => child.announce((options.announcedPort ?? developmentPort) || 43123))
    return child
  }
  const manager = new PythonBackendManager({
    executable: 'C:\\Python\\python.exe',
    argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
    projectRoot: 'C:\\NetConsole',
    dataRoot: 'C:\\Users\\tester\\AppData\\Local\\NetConsole\\Development',
    runtimeMode: options.runtimeMode ?? 'desktop-development',
    pythonPath: 'C:\\NetConsole\\src',
    startupTimeoutMs: 50,
    stopTimeoutMs: 5,
    pollIntervalMs: 1,
    createToken: () => TOKEN,
    delay: async () => undefined,
    spawnProcess,
    fetchImpl: options.fetchImpl ?? vi.fn(async (_url, request) => {
      expect(new Headers(request?.headers).get(DESKTOP_SESSION_HEADER)).toBe(TOKEN)
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as typeof fetch,
    logger: options.logger,
    awaitProcessExit: options.awaitProcessExit,
    environment: options.environment,
  })
  return { manager, child, spawnCalls }
}

describe('PythonBackendManager', () => {
  it('starts once, sends the token through stdin, and uses a shell-free hidden child', async () => {
    const { manager, child, spawnCalls } = createManager()
    let handshake = ''
    child.stdin.on('data', (chunk) => { handshake += chunk.toString('utf8') })

    const [first, second] = await Promise.all([manager.start(), manager.start()])

    expect(first).toEqual(second)
    expect(first.baseUrl).toBe('http://127.0.0.1:43123')
    expect(spawnCalls).toHaveLength(1)
    expect(spawnCalls[0].args).not.toContain(TOKEN)
    expect(spawnCalls[0].args).toContain('0')
    expect(spawnCalls[0].options.shell).toBe(false)
    expect(spawnCalls[0].options.windowsHide).toBe(true)
    expect((spawnCalls[0].options.env as NodeJS.ProcessEnv).NETCONSOLE_DATA_ROOT).toBe(
      'C:\\Users\\tester\\AppData\\Local\\NetConsole\\Development',
    )
    expect((spawnCalls[0].options.env as NodeJS.ProcessEnv).NETCONSOLE_RUNTIME_MODE).toBe(
      'desktop-development',
    )
    expect((spawnCalls[0].options.env as NodeJS.ProcessEnv).PYTHONUTF8).toBe('1')
    expect((spawnCalls[0].options.env as NodeJS.ProcessEnv).PYTHONIOENCODING).toBe('utf-8')
    expect(JSON.parse(handshake).session_token).toBe(TOKEN)
    expect(manager.getStatus()).toEqual({ state: 'ready', baseUrl: first.baseUrl })

    await manager.stop()

    expect(child.signals).toEqual([])
    expect(manager.getStatus()).toEqual({ state: 'stopped' })
  })

  it('enables the fixed loopback development API only with an explicit development environment', async () => {
    const developmentToken = 'codex-development-token-abcdefghijklmnopqrstuvwxyz'
    const { manager, child, spawnCalls } = createManager({
      fetchImpl: vi.fn(async (_url, request) => {
        expect(new Headers(request?.headers).get(DESKTOP_SESSION_HEADER)).toBe(developmentToken)
        return new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }) as typeof fetch,
      environment: {
        NETCONSOLE_DEV_MODE: '1',
        NETCONSOLE_DEV_BACKEND_PORT: '8000',
        NETCONSOLE_DEV_SESSION_TOKEN: developmentToken,
      },
    })
    let handshake = ''
    child.stdin.on('data', (chunk) => { handshake += chunk.toString('utf8') })

    await manager.start()

    expect(spawnCalls[0].args).toContain('--dev-mode')
    expect(spawnCalls[0].args).toContain('8000')
    expect(spawnCalls[0].args).not.toContain(developmentToken)
    expect((spawnCalls[0].options.env as NodeJS.ProcessEnv).NETCONSOLE_DEV_SESSION_TOKEN).toBeUndefined()
    expect(JSON.parse(handshake).session_token).toBe(developmentToken)
    await manager.stop()
  })

  it('never enables development endpoints for the packaged runtime', async () => {
    const { manager, spawnCalls } = createManager({
      runtimeMode: 'desktop-packaged',
      environment: {
        NETCONSOLE_DEV_MODE: '1',
        NETCONSOLE_DEV_BACKEND_PORT: '8000',
        NETCONSOLE_DEV_SESSION_TOKEN: 'codex-development-token-abcdefghijklmnopqrstuvwxyz',
      },
    })

    await manager.start()

    expect(spawnCalls[0].args).not.toContain('--dev-mode')
    expect(spawnCalls[0].args).toContain('0')
    await manager.stop()
  })

  it('rejects an invalid fixed development backend port before spawning', async () => {
    const { manager, spawnCalls } = createManager({
      environment: {
        NETCONSOLE_DEV_MODE: '1',
        NETCONSOLE_DEV_BACKEND_PORT: '70000',
      },
    })

    await expect(manager.start()).rejects.toThrow('between 1 and 65535')
    expect(spawnCalls).toHaveLength(0)
  })

  it('rejects a backend announcement that differs from the fixed development port', async () => {
    const { manager } = createManager({
      announcedPort: 43123,
      environment: {
        NETCONSOLE_DEV_MODE: '1',
        NETCONSOLE_DEV_BACKEND_PORT: '8000',
      },
    })

    await expect(manager.start()).rejects.toThrow('unexpected fixed development port')
  })

  it('reports an unexpected exit after readiness', async () => {
    const { manager, child } = createManager()
    const statuses: string[] = []
    manager.onStatusChange((status) => statuses.push(status.state))
    await manager.waitUntilReady()

    child.exit(7)

    expect(manager.getStatus().state).toBe('failed')
    expect(manager.getStatus().error).toContain('code=7')
    expect(manager.getStatus()).not.toHaveProperty('baseUrl')
    expect(() => manager.getRuntimeInfo()).toThrow('not ready')
    expect(statuses).toEqual(['starting', 'ready', 'failed'])
  })

  it('stops after an acknowledgement even when Windows misses the child exit event', async () => {
    const child = new FakeChild(false)
    child.stdin.on('data', (chunk) => {
      if (chunk.toString('utf8').includes('"command":"shutdown"')) {
        child.stdout.write('{"event":"netconsole.electron_backend.shutdown_ack"}\n')
      }
    })
    const { manager } = createManager({ child, awaitProcessExit: false })

    await manager.start()
    await manager.stop()

    expect(child.signals).toEqual([])
    expect(manager.getStatus()).toEqual({ state: 'stopped' })
  })

  it('moves to failed when setup fails before a child is spawned', async () => {
    const spawnProcess = vi.fn()
    const manager = new PythonBackendManager({
      executable: 'python.exe',
      argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      projectRoot: 'C:\\NetConsole',
      dataRoot: 'C:\\NetConsoleData',
      runtimeMode: 'desktop-development',
      createToken: () => 'invalid',
      spawnProcess,
    })

    await expect(manager.start()).rejects.toThrow('invalid token')
    expect(spawnProcess).not.toHaveBeenCalled()
    expect(manager.getStatus()).toEqual({
      state: 'failed',
      error: 'Python backend token generator returned an invalid token',
    })
  })

  it('fails clearly when the child cannot start', async () => {
    const child = new FakeChild(false)
    const { manager } = createManager({
      child,
      fetchImpl: vi.fn(async () => {
        child.emit('error', new Error('spawn failed'))
        throw new Error('connection refused')
      }) as typeof fetch,
    })

    await expect(manager.start()).rejects.toThrow('spawn failed')
    expect(manager.getStatus().state).toBe('failed')
  })

  it('fails on a health timeout and stops only its owned child', async () => {
    const child = new FakeChild(false)
    const manager = new PythonBackendManager({
      executable: 'python.exe',
      argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      projectRoot: 'C:\\NetConsole',
      dataRoot: 'C:\\NetConsoleData',
      runtimeMode: 'desktop-development',
      startupTimeoutMs: 2,
      stopTimeoutMs: 1,
      pollIntervalMs: 1,
      createToken: () => TOKEN,
      spawnProcess: () => {
        queueMicrotask(() => child.announce())
        return child
      },
      fetchImpl: vi.fn(async () => { throw new Error('not ready') }) as typeof fetch,
    })

    await expect(manager.start()).rejects.toThrow('health check timed out')
    expect(child.signals[0]).toBe('SIGKILL')
    expect(manager.getStatus().state).toBe('failed')
  })

  it('does not report stopped when its owned child cannot be terminated', async () => {
    const child = new FakeChild(false, false)
    const { manager, spawnCalls } = createManager({ child })
    await manager.start()

    await expect(manager.stop()).rejects.toThrow('did not acknowledge shutdown')
    await expect(manager.start()).rejects.toThrow('still running after a failed stop')

    expect(child.signals).toEqual(['SIGTERM', 'SIGKILL'])
    expect(spawnCalls).toHaveLength(1)
    expect(manager.getStatus().state).toBe('failed')
  })

  it('redacts a token even if the child writes it to output', async () => {
    const logs: string[] = []
    const { manager, child } = createManager({
      logger: (event, detail) => logs.push(`${event} ${detail ?? ''}`),
    })
    const start = manager.start()
    child.stdout.write(`session_token=${TOKEN}\n`)
    await start
    await manager.stop()

    expect(logs.join('\n')).not.toContain(TOKEN)
    expect(logs.join('\n')).toContain('session_token=***')
  })
})
