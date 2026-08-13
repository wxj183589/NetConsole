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
  pid?: number
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
          this.stdout.write('{"event":"netconsole.electron_backend.shutdown_received"}\n')
          this.stdout.write('{"event":"netconsole.electron_backend.shutdown_complete"}\n')
          this.stdin.on('data', (exitChunk) => {
            if (exitChunk.toString('utf8').includes('"command":"exit"')) queueMicrotask(() => this.exit(0))
          })
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

  announceStartupFailure(message: string): void {
    this.stdout.write(`${JSON.stringify({
      event: 'netconsole.electron_backend.startup_failed',
      message,
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
  startupFailure?: string
  startupTimeoutMs?: number
  startupHardTimeoutMs?: number
  delay?: (milliseconds: number) => Promise<void>
  autoAnnounce?: boolean
  shutdownAckTimeoutMs?: number
  shutdownGracefulTimeoutMs?: number
  processExitTimeoutMs?: number
  onShutdownProgress?: (progress: { phase: string; activeTasks?: number; activeWorkers?: number }) => void
} = {}) {
  const child = options.child ?? new FakeChild()
  const spawnCalls: Array<{ command: string; args: string[]; options: Record<string, unknown> }> = []
  const spawnProcess: SpawnProcess = (command, args, spawnOptions) => {
    spawnCalls.push({ command, args, options: spawnOptions as Record<string, unknown> })
    const developmentPort = options.runtimeMode !== 'desktop-packaged'
      && options.environment?.NETCONSOLE_DEV_MODE === '1'
      ? Number(options.environment.NETCONSOLE_DEV_BACKEND_PORT || 0)
      : 0
    queueMicrotask(() => {
      if (options.autoAnnounce === false) return
      if (options.startupFailure) child.announceStartupFailure(options.startupFailure)
      else child.announce((options.announcedPort ?? developmentPort) || 43123)
    })
    return child
  }
  const manager = new PythonBackendManager({
    executable: 'C:\\Python\\python.exe',
    argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
    projectRoot: 'C:\\NetConsole',
    dataRoot: 'D:\\NetConsoleData',
    runtimeMode: options.runtimeMode ?? 'desktop-development',
    pythonPath: 'C:\\NetConsole\\src',
    startupTimeoutMs: options.startupTimeoutMs ?? 50,
    startupHardTimeoutMs: options.startupHardTimeoutMs,
    shutdownAckTimeoutMs: options.shutdownAckTimeoutMs,
    shutdownGracefulTimeoutMs: options.shutdownGracefulTimeoutMs,
    processExitTimeoutMs: options.processExitTimeoutMs,
    stopTimeoutMs: 5,
    pollIntervalMs: 1,
    createToken: () => TOKEN,
    delay: options.delay ?? (async () => undefined),
    spawnProcess,
    fetchImpl: options.fetchImpl ?? vi.fn(async (_url, request) => {
      expect(new Headers(request?.headers).get(DESKTOP_SESSION_HEADER)).toBe(TOKEN)
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as typeof fetch,
    logger: options.logger,
    onShutdownProgress: options.onShutdownProgress,
    awaitProcessExit: options.awaitProcessExit,
    environment: options.environment,
  })
  return { manager, child, spawnCalls }
}

describe('PythonBackendManager', () => {
  it('surfaces a backend data-root conflict before the listening handshake', async () => {
    const message = 'D:\\NetConsoleData 当前已由另一个 NetConsole Backend 使用。'
    const { manager } = createManager({ startupFailure: message })

    await expect(manager.start()).rejects.toThrow(message)
  })

  it('surfaces startup failure after listening without waiting for a health timeout', async () => {
    const child = new FakeChild(false)
    const fetchImpl = vi.fn(async () => {
      child.announceStartupFailure('application build failed')
      throw new Error('not ready')
    }) as typeof fetch
    const { manager } = createManager({ child, fetchImpl, startupTimeoutMs: 10_000 })

    await expect(manager.start()).rejects.toThrow('application build failed')

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(manager.getStatus().state).toBe('failed')
  })

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
      'D:\\NetConsoleData',
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

  it('escalates after a lifecycle acknowledgement when the child never exits', async () => {
    const child = new FakeChild(false)
    child.stdin.on('data', (chunk) => {
      if (chunk.toString('utf8').includes('"command":"shutdown"')) {
        child.stdout.write('{"event":"netconsole.electron_backend.shutdown_received"}\n')
        child.stdout.write('{"event":"netconsole.electron_backend.shutdown_complete"}\n')
      }
    })
    const { manager } = createManager({ child })

    await manager.start()
    await manager.stop()

    expect(child.signals).toContain('SIGTERM')
    expect(manager.getStatus().state).toBe('stopped')
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

    await expect(manager.start()).rejects.toThrow('stage watchdog')
    expect(child.signals[0]).toBe('SIGTERM')
    expect(manager.getStatus().state).toBe('failed')
  })

  it('does not report stopped when its owned child cannot be terminated', async () => {
    const child = new FakeChild(false, false)
    const { manager, spawnCalls } = createManager({ child })
    await manager.start()

    await expect(manager.stop()).rejects.toThrow('did not exit after termination escalation')
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

  it('does not escalate while graceful shutdown is still draining', async () => {
    vi.useFakeTimers()
    try {
      const child = new FakeChild(false)
      child.stdin.on('data', (chunk) => {
        if (!chunk.toString('utf8').includes('"command":"shutdown"')) return
        child.stdout.write('{"event":"netconsole.electron_backend.shutdown_received"}\n')
        setTimeout(() => child.stdout.write('{"event":"netconsole.electron_backend.shutdown_complete"}\n'), 20_000)
        child.stdin.on('data', (exitChunk) => {
          if (exitChunk.toString('utf8').includes('"command":"exit"')) queueMicrotask(() => child.exit(0))
        })
      })
      const { manager } = createManager({ child })
      await manager.start()
      const stopping = manager.stop()
      await vi.advanceTimersByTimeAsync(15_000)
      expect(child.signals).toEqual([])
      await vi.advanceTimersByTimeAsync(5_000)
      await stopping
      expect(child.signals).toEqual([])
      expect(manager.getStatus().state).toBe('stopped')
    } finally {
      vi.useRealTimers()
    }
  })

  it('cancels a pre-handshake startup without waiting for the startup watchdog', async () => {
    const child = new FakeChild(false)
    const { manager } = createManager({
      child,
      startupTimeoutMs: 60_000,
      startupHardTimeoutMs: 60_000,
      autoAnnounce: false,
      delay: () => new Promise(() => undefined),
      fetchImpl: vi.fn() as typeof fetch,
    })
    const starting = manager.start()
    await Promise.resolve()
    const stopped = manager.stop()
    await stopped
    await expect(starting).rejects.toThrow()
    expect(child.signals.length).toBeGreaterThan(0)
    expect(manager.getStatus().state).toBe('stopped')
  })

  it('cancels a slow application build health wait and terminates its startup child', async () => {
    const child = new FakeChild(false)
    const fetchImpl = vi.fn((_url: string | URL | Request, request?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      request?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    })) as typeof fetch
    const { manager } = createManager({
      child,
      startupTimeoutMs: 60_000,
      startupHardTimeoutMs: 60_000,
      fetchImpl,
    })
    const starting = manager.start()
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalled())
    await manager.stop()
    await expect(starting).rejects.toThrow('cancelled')
    expect(child.signals.length).toBeGreaterThan(0)
    expect(manager.getStatus().state).toBe('stopped')
  })

  it('allows a disk-heavy startup stage to make valid progress after thirty seconds', async () => {
    vi.useFakeTimers()
    try {
      let releaseSlowStage: (() => void) | undefined
      let healthAttempts = 0
      const { manager, child } = createManager({
        startupTimeoutMs: 30_000,
        startupHardTimeoutMs: 60_000,
        delay: () => new Promise<void>((resolvePromise) => { releaseSlowStage = resolvePromise }),
        fetchImpl: vi.fn(async () => {
          healthAttempts += 1
          if (healthAttempts === 1) throw new Error('application is still building')
          return new Response(JSON.stringify({ status: 'ok' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }) as typeof fetch,
      })
      const starting = manager.start()
      child.stdout.write('{"event":"netconsole.electron_backend.startup_stage","stage":"active_site_database_initializing","elapsed_ms":1}\n')
      await vi.advanceTimersByTimeAsync(31_000)
      expect(manager.getStatus().state).toBe('starting')
      releaseSlowStage?.()
      await starting
      expect(manager.getStatus().state).toBe('ready')
      await manager.stop()
    } finally {
      vi.useRealTimers()
    }
  })

  it('supports twenty complete start-run-stop-restart lifecycle rounds', async () => {
    const children: FakeChild[] = []
    const manager = new PythonBackendManager({
      executable: 'python.exe',
      argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      projectRoot: 'C:\\NetConsole',
      dataRoot: 'D:\\NetConsoleData',
      runtimeMode: 'desktop-development',
      startupTimeoutMs: 100,
      pollIntervalMs: 1,
      createToken: () => TOKEN,
      spawnProcess: () => {
        const child = new FakeChild()
        children.push(child)
        queueMicrotask(() => child.announce(43_000 + children.length))
        return child
      },
      fetchImpl: vi.fn(async () => new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch,
    })

    for (let round = 0; round < 20; round += 1) {
      await manager.start()
      expect(manager.getStatus().state).toBe('ready')
      await manager.stop()
      expect(manager.getStatus().state).toBe('stopped')
    }
    expect(children).toHaveLength(20)
    expect(children.every((child) => child.exitCode === 0)).toBe(true)
  })

  it('logs the owned backend process exit with pid, code, and signal', async () => {
    const logs: string[] = []
    const { manager, child } = createManager({
      logger: (event, detail) => logs.push(`${event} ${detail ?? ''}`),
    })
    child.pid = 24680

    await manager.start()
    await manager.stop()

    expect(logs).toContain('ELECTRON_BACKEND_PROCESS_EXITED pid=24680 code=0 signal=none')
  })
})
