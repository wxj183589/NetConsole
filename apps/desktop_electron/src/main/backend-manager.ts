import { spawn as spawnChild } from 'node:child_process'
import type { SpawnOptionsWithoutStdio } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { delimiter } from 'node:path'
import type { Readable, Writable } from 'node:stream'

import {
  DESKTOP_SESSION_HEADER,
  type BackendStatus,
} from '../shared/bridge'
import { redactSensitiveText, type DesktopLogger } from './logger'

export interface BackendRuntimeInfo {
  baseUrl: string
  apiToken: string
}

export interface ManagedChildProcess extends EventEmitter {
  pid?: number
  stdin: Writable
  stdout: Readable
  stderr: Readable
  exitCode: number | null
  kill(signal?: NodeJS.Signals | number): boolean
}

export type SpawnProcess = (
  command: string,
  args: string[],
  options: SpawnOptionsWithoutStdio,
) => ManagedChildProcess

export interface PythonBackendManagerOptions {
  executable: string
  argumentsPrefix: string[]
  projectRoot: string
  dataRoot: string
  runtimeMode: 'desktop-development' | 'desktop-packaged'
  pythonPath?: string
  rendererOrigin?: string
  startupTimeoutMs?: number
  stopTimeoutMs?: number
  pollIntervalMs?: number
  environment?: NodeJS.ProcessEnv
  spawnProcess?: SpawnProcess
  fetchImpl?: typeof fetch
  createToken?: () => string
  delay?: (milliseconds: number) => Promise<void>
  awaitProcessExit?: boolean
  logger?: DesktopLogger
}

export class PythonBackendManager {
  private state: BackendStatus['state'] = 'stopped'
  private runtime?: BackendRuntimeInfo
  private error?: string
  private child?: ManagedChildProcess
  private startPromise?: Promise<BackendRuntimeInfo>
  private stopPromise?: Promise<void>
  private stopRequested = false
  private startupFailure?: Error
  private readonly expectedExit = new WeakSet<ManagedChildProcess>()
  private readonly listeners = new Set<(status: BackendStatus) => void>()
  private readonly shutdownAckListeners = new Set<(child: ManagedChildProcess) => void>()
  private readonly options: Required<Pick<
    PythonBackendManagerOptions,
    'startupTimeoutMs' | 'stopTimeoutMs' | 'pollIntervalMs' | 'spawnProcess' | 'fetchImpl' | 'createToken' | 'delay' | 'awaitProcessExit' | 'logger'
  >> & PythonBackendManagerOptions

  constructor(options: PythonBackendManagerOptions) {
    this.options = {
      ...options,
      startupTimeoutMs: options.startupTimeoutMs ?? 15_000,
      stopTimeoutMs: options.stopTimeoutMs ?? 5_000,
      pollIntervalMs: options.pollIntervalMs ?? 100,
      spawnProcess: options.spawnProcess ?? defaultSpawn,
      fetchImpl: options.fetchImpl ?? fetch,
      createToken: options.createToken ?? (() => randomBytes(32).toString('base64url')),
      delay: options.delay ?? ((milliseconds) => new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds))),
      awaitProcessExit: options.awaitProcessExit ?? !process.versions.electron,
      logger: options.logger ?? (() => undefined),
    }
  }

  start(): Promise<BackendRuntimeInfo> {
    if (this.state === 'ready' && this.runtime) return Promise.resolve({ ...this.runtime })
    if (this.startPromise) return this.startPromise
    if (this.stopPromise) return this.stopPromise.then(() => this.start())
    if (this.child?.exitCode === null) {
      return Promise.reject(new Error('Python backend process is still running after a failed stop'))
    }
    this.stopRequested = false
    this.startPromise = this.startInternal()
      .catch((cause) => {
        const message = this.safeError(cause, this.runtime?.apiToken ?? '')
        if (!this.stopRequested && this.state !== 'failed') {
          this.error = message
          this.runtime = undefined
          this.transition('failed')
          this.options.logger('ELECTRON_BACKEND_START_FAILED', message)
        }
        throw cause instanceof Error && cause.message === message
          ? cause
          : new Error(message)
      })
      .finally(() => {
        this.startPromise = undefined
      })
    return this.startPromise
  }

  waitUntilReady(): Promise<BackendRuntimeInfo> {
    return this.start()
  }

  getRuntimeInfo(): BackendRuntimeInfo {
    if (this.state !== 'ready' || !this.runtime) throw new Error('Python backend is not ready')
    return { ...this.runtime }
  }

  getStatus(): BackendStatus {
    return {
      state: this.state,
      ...(this.runtime ? { baseUrl: this.runtime.baseUrl } : {}),
      ...(this.error ? { error: this.error } : {}),
    }
  }

  onStatusChange(listener: (status: BackendStatus) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  stop(): Promise<void> {
    if (this.stopPromise) return this.stopPromise
    this.stopRequested = true
    this.stopPromise = this.stopInternal().finally(() => {
      this.stopPromise = undefined
    })
    return this.stopPromise
  }

  private async startInternal(): Promise<BackendRuntimeInfo> {
    this.startupFailure = undefined
    this.error = undefined
    this.transition('starting')
    const apiToken = this.options.createToken()
    if (!/^[A-Za-z0-9_-]{32,256}$/.test(apiToken)) {
      throw new Error('Python backend token generator returned an invalid token')
    }
    const args = [
      ...this.options.argumentsPrefix,
      '--host',
      '127.0.0.1',
      '--port',
      '0',
      ...(this.options.rendererOrigin ? ['--renderer-origin', this.options.rendererOrigin] : []),
    ]
    const environment: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.options.environment,
      PYTHONUNBUFFERED: '1',
      NETCONSOLE_DATA_ROOT: this.options.dataRoot,
      NETCONSOLE_RUNTIME_MODE: this.options.runtimeMode,
    }
    if (this.options.pythonPath) {
      const existingPythonPath = this.options.environment?.PYTHONPATH ?? process.env.PYTHONPATH
      environment.PYTHONPATH = existingPythonPath
        ? `${this.options.pythonPath}${delimiter}${existingPythonPath}`
        : this.options.pythonPath
    } else {
      delete environment.PYTHONPATH
    }

    let child: ManagedChildProcess | undefined
    try {
      child = this.options.spawnProcess(this.options.executable, args, {
        cwd: this.options.projectRoot,
        env: environment,
        shell: false,
        windowsHide: true,
        stdio: 'pipe',
      })
      this.child = child
      this.attachProcessHandlers(child, apiToken)
      const runtimeAnnouncement = this.waitForRuntimeAnnouncement(child, apiToken)
      child.stdin.write(`${JSON.stringify({ session_token: apiToken })}\n`, 'utf8')
      const runtime = await runtimeAnnouncement
      this.runtime = runtime
      await this.pollUntilReady(child, runtime)
      if (this.stopRequested) throw new Error('Python backend startup was cancelled')
      this.error = undefined
      this.transition('ready')
      this.options.logger('ELECTRON_BACKEND_READY', `base_url=${runtime.baseUrl}`)
      return { ...runtime }
    } catch (cause) {
      const message = this.safeError(cause, apiToken)
      if (!this.stopRequested) {
        this.error = message
        this.transition('failed')
        this.options.logger('ELECTRON_BACKEND_START_FAILED', message)
      }
      if (child) {
        try {
          await this.terminateOwnedChild(child, false)
        } catch (cleanupCause) {
          const cleanupMessage = this.safeError(cleanupCause, apiToken)
          this.error = `${message}; ${cleanupMessage}`
          this.options.logger('ELECTRON_BACKEND_CLEANUP_FAILED', cleanupMessage)
        }
      }
      this.runtime = undefined
      throw new Error(this.error ?? message)
    }
  }

  private waitForRuntimeAnnouncement(
    child: ManagedChildProcess,
    apiToken: string,
  ): Promise<BackendRuntimeInfo> {
    return new Promise((resolvePromise, reject) => {
      let settled = false
      const timeout = setTimeout(
        () => finish(new Error(`Python backend port handshake timed out after ${this.options.startupTimeoutMs}ms`)),
        this.options.startupTimeoutMs,
      )
      const onError = (cause: Error) => finish(cause)
      const onExit = (code: number | null, signal: NodeJS.Signals | null) => finish(
        new Error(`Python backend exited before port handshake (code=${code ?? 'none'}, signal=${signal ?? 'none'})`),
      )
      const finish = (cause?: Error, runtime?: BackendRuntimeInfo): void => {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        child.removeListener('error', onError)
        child.removeListener('exit', onExit)
        if (cause) reject(cause)
        else resolvePromise(runtime!)
      }
      child.once('error', onError)
      child.once('exit', onExit)
      attachLineLogger(child.stdout, 'stdout', apiToken, this.options.logger, (line) => {
        let payload: unknown
        try {
          payload = JSON.parse(line)
        } catch {
          return
        }
        if (isShutdownAcknowledgement(payload)) {
          for (const listener of this.shutdownAckListeners) listener(child)
          return
        }
        if (settled) return
        if (!isRuntimeAnnouncement(payload)) return
        finish(undefined, {
          baseUrl: `http://127.0.0.1:${payload.port}`,
          apiToken,
        })
      })
    })
  }

  private async pollUntilReady(
    child: ManagedChildProcess,
    runtime: BackendRuntimeInfo,
  ): Promise<void> {
    const deadline = Date.now() + this.options.startupTimeoutMs
    while (Date.now() < deadline) {
      if (this.stopRequested) throw new Error('Python backend startup was cancelled')
      if (this.startupFailure) throw this.startupFailure
      if (this.child !== child || child.exitCode !== null) {
        throw new Error('Python backend exited before becoming ready')
      }
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), Math.min(1_000, this.options.pollIntervalMs * 5))
      try {
        const response = await this.options.fetchImpl(`${runtime.baseUrl}/api/health`, {
          cache: 'no-store',
          headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
          signal: controller.signal,
        })
        if (response.ok) {
          const payload = await response.json() as { status?: unknown }
          if (payload.status === 'ok') return
        }
      } catch {
        // 连接拒绝和启动期短超时均由下一轮重试处理。
      } finally {
        clearTimeout(timeout)
      }
      await this.options.delay(this.options.pollIntervalMs)
    }
    throw new Error(`Python backend health check timed out after ${this.options.startupTimeoutMs}ms`)
  }

  private attachProcessHandlers(child: ManagedChildProcess, apiToken: string): void {
    attachLineLogger(child.stderr, 'stderr', apiToken, this.options.logger)
    child.stdin.once('error', (cause: Error) => {
      if (this.expectedExit.has(child)) return
      const message = this.safeError(cause, apiToken)
      this.startupFailure = new Error(message)
      if (this.state === 'ready') {
        this.error = message
        this.runtime = undefined
        this.transition('failed')
      }
    })
    child.once('error', (cause: Error) => {
      if (this.expectedExit.has(child)) return
      const message = this.safeError(cause, apiToken)
      this.startupFailure = new Error(message)
      if (this.state === 'ready') {
        this.error = message
        this.runtime = undefined
        this.transition('failed')
      }
    })
    child.once('exit', (code: number | null, signal: NodeJS.Signals | null) => {
      if (this.child === child) this.child = undefined
      if (this.expectedExit.has(child)) return
      const detail = `Python backend exited unexpectedly (code=${code ?? 'none'}, signal=${signal ?? 'none'})`
      this.startupFailure = new Error(detail)
      if (this.state === 'ready') {
        this.error = detail
        this.runtime = undefined
        this.transition('failed')
        this.options.logger('ELECTRON_BACKEND_UNEXPECTED_EXIT', detail)
      }
    })
  }

  private async stopInternal(): Promise<void> {
    const child = this.child
    if (child) {
      this.options.logger('ELECTRON_BACKEND_STOPPING')
      try {
        await this.terminateOwnedChild(child, this.state === 'ready')
      } catch (cause) {
        const message = this.safeError(cause, this.runtime?.apiToken ?? '')
        this.runtime = undefined
        this.error = message
        this.transition('failed')
        this.options.logger('ELECTRON_BACKEND_STOP_FAILED', message)
        throw new Error(message)
      }
    }
    this.child = undefined
    this.runtime = undefined
    this.error = undefined
    this.transition('stopped')
    this.options.logger('ELECTRON_BACKEND_STOPPED')
  }

  private async terminateOwnedChild(
    child: ManagedChildProcess,
    graceful: boolean,
  ): Promise<void> {
    this.expectedExit.add(child)
    if (child.exitCode !== null) {
      child.stdin.end()
      return
    }
    if (!graceful) {
      child.stdin.end()
      child.kill('SIGKILL')
      return
    }
    let ackListener!: (value: ManagedChildProcess) => void
    const acknowledgement = new Promise<boolean>((resolvePromise) => {
      ackListener = (value) => {
        if (value === child) resolvePromise(true)
      }
      this.shutdownAckListeners.add(ackListener)
    })
    const timeout = this.options.delay(this.options.stopTimeoutMs).then(() => false)
    try {
      child.stdin.write(`${JSON.stringify({ command: 'shutdown' })}\n`, 'utf8')
      this.options.logger('ELECTRON_BACKEND_SHUTDOWN_SENT')
    } catch {
      this.shutdownAckListeners.delete(ackListener)
      child.stdin.end()
      child.kill('SIGKILL')
      return
    }
    const acknowledged = await Promise.race([acknowledgement, timeout])
    this.shutdownAckListeners.delete(ackListener)
    if (acknowledged) {
      this.options.logger('ELECTRON_BACKEND_SHUTDOWN_ACKNOWLEDGED')
      const processExit = this.options.awaitProcessExit
        ? this.waitForProcessExit(child)
        : undefined
      child.stdin.write(`${JSON.stringify({ command: 'exit' })}\n`, 'utf8')
      child.stdin.end()
      this.options.logger('ELECTRON_BACKEND_CONTROL_CLOSED')
      await processExit
      this.options.logger('ELECTRON_BACKEND_PROCESS_RELEASED')
      return
    }
    child.stdin.end()
    this.options.logger('ELECTRON_BACKEND_CONTROL_CLOSED')
    this.options.logger('ELECTRON_BACKEND_SHUTDOWN_ACK_TIMEOUT')
    const terminated = child.kill('SIGTERM')
    if (!terminated && child.exitCode === null && !child.kill('SIGKILL')) {
      throw new Error('Python backend did not acknowledge shutdown or accept termination')
    }
  }

  private waitForProcessExit(child: ManagedChildProcess): Promise<void> {
    if (child.exitCode !== null) return Promise.resolve()
    return new Promise((resolvePromise) => {
      let settled = false
      const finish = (): void => {
        if (settled) return
        settled = true
        child.removeListener('exit', finish)
        child.removeListener('close', finish)
        resolvePromise()
      }
      child.once('exit', finish)
      child.once('close', finish)
    })
  }

  private transition(state: BackendStatus['state']): void {
    this.state = state
    const snapshot = this.getStatus()
    for (const listener of this.listeners) listener(snapshot)
  }

  private safeError(cause: unknown, apiToken: string): string {
    const message = cause instanceof Error ? cause.message : String(cause)
    return redactSensitiveText(message, [apiToken]) || 'Python backend failed'
  }
}

function defaultSpawn(
  command: string,
  args: string[],
  options: SpawnOptionsWithoutStdio,
): ManagedChildProcess {
  return spawnChild(command, args, options) as ManagedChildProcess
}

function attachLineLogger(
  stream: Readable,
  source: string,
  secret: string,
  logger: DesktopLogger,
  onLine?: (line: string) => void,
): void {
  let pending = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk: string) => {
    pending += chunk
    const lines = pending.split(/\r?\n/)
    pending = lines.pop() ?? ''
    for (const line of lines) {
      onLine?.(line)
      const safe = redactSensitiveText(line, [secret])
      if (safe) logger('ELECTRON_BACKEND_OUTPUT', `${source}: ${safe}`)
    }
  })
  stream.on('end', () => {
    if (pending) onLine?.(pending)
    const safe = redactSensitiveText(pending, [secret])
    if (safe) logger('ELECTRON_BACKEND_OUTPUT', `${source}: ${safe}`)
  })
}

function isRuntimeAnnouncement(value: unknown): value is {
  event: 'netconsole.electron_backend.listening'
  host: '127.0.0.1'
  port: number
} {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const payload = value as Record<string, unknown>
  return payload.event === 'netconsole.electron_backend.listening'
    && payload.host === '127.0.0.1'
    && Number.isInteger(payload.port)
    && Number(payload.port) >= 1
    && Number(payload.port) <= 65535
}

function isShutdownAcknowledgement(value: unknown): boolean {
  return typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
    && (value as Record<string, unknown>).event === 'netconsole.electron_backend.shutdown_ack'
}
