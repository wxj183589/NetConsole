import { spawn as spawnChild } from 'node:child_process'
import type { SpawnOptionsWithoutStdio } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { delimiter, isAbsolute } from 'node:path'
import type { Readable, Writable } from 'node:stream'

import {
  DESKTOP_SESSION_HEADER,
  type BackendStatus,
} from '../shared/bridge'
import { redactSensitiveText, type DesktopLogger } from './logger'
import type { StartupMilestone } from './startup-timeline'
import type { DesktopStorageMode } from './development-data-root'

export interface BackendRuntimeInfo {
  baseUrl: string
  apiToken: string
}

export interface BackendStartupProgress {
  stage: string
  elapsedMs: number
  pid?: number
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
  activeSiteId?: string
  runtimeMode: 'desktop-development' | 'desktop-packaged'
  storageMode?: DesktopStorageMode
  pythonPath?: string
  rendererOrigin?: string
  startupTimeoutMs?: number
  startupHardTimeoutMs?: number
  stopTimeoutMs?: number
  pollIntervalMs?: number
  environment?: NodeJS.ProcessEnv
  spawnProcess?: SpawnProcess
  fetchImpl?: typeof fetch
  createToken?: () => string
  delay?: (milliseconds: number) => Promise<void>
  /** Retained for test/config compatibility; production always waits for exit. */
  awaitProcessExit?: boolean
  forceTerminateProcessTree?: (pid: number) => Promise<boolean>
  logger?: DesktopLogger
  onStartupMilestone?: (event: Extract<StartupMilestone, `backend.${string}`>) => void
  onStartupProgress?: (progress: BackendStartupProgress) => void
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
  private startupStage?: string
  private startupStageElapsedMs?: number
  private startupStartedAt?: number
  private startupLastProgressAt?: number
  private readonly expectedExit = new WeakSet<ManagedChildProcess>()
  private readonly shutdownReceived = new WeakSet<ManagedChildProcess>()
  private readonly shutdownComplete = new WeakSet<ManagedChildProcess>()
  private readonly listeners = new Set<(status: BackendStatus) => void>()
  private readonly shutdownReceivedListeners = new Set<(child: ManagedChildProcess) => void>()
  private readonly shutdownCompleteListeners = new Set<(child: ManagedChildProcess) => void>()
  private readonly options: Required<Pick<
    PythonBackendManagerOptions,
    'startupTimeoutMs' | 'startupHardTimeoutMs' | 'stopTimeoutMs' | 'pollIntervalMs' | 'spawnProcess' | 'fetchImpl' | 'createToken' | 'delay' | 'forceTerminateProcessTree' | 'logger'
  >> & PythonBackendManagerOptions

  constructor(options: PythonBackendManagerOptions) {
    this.options = {
      ...options,
      startupTimeoutMs: options.startupTimeoutMs ?? 30_000,
      startupHardTimeoutMs: options.startupHardTimeoutMs ?? Math.max(60_000, (options.startupTimeoutMs ?? 30_000) * 2),
      stopTimeoutMs: options.stopTimeoutMs ?? 5_000,
      pollIntervalMs: options.pollIntervalMs ?? 100,
      spawnProcess: options.spawnProcess ?? defaultSpawn,
      fetchImpl: options.fetchImpl ?? fetch,
      createToken: options.createToken ?? (() => randomBytes(32).toString('base64url')),
      delay: options.delay ?? ((milliseconds) => new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds))),
      forceTerminateProcessTree: options.forceTerminateProcessTree ?? defaultForceTerminateProcessTree,
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
    const waitForStart = this.startPromise
      ? this.startPromise.catch(() => undefined)
      : Promise.resolve()
    this.stopPromise = waitForStart.then(() => this.stopInternal()).finally(() => {
      this.stopPromise = undefined
    })
    return this.stopPromise
  }

  configureStorage(dataRoot: string, activeSiteId: string): void {
    if (this.child?.exitCode === null || this.state !== 'stopped') {
      throw new Error('Python backend must be stopped before storage reconfiguration')
    }
    if (!isAbsolute(dataRoot) || /[\u0000-\u001f]/.test(dataRoot)) throw new TypeError('dataRoot is invalid')
    if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(activeSiteId)) throw new TypeError('activeSiteId is invalid')
    this.options.dataRoot = dataRoot
    this.options.activeSiteId = activeSiteId
  }

  private async startInternal(): Promise<BackendRuntimeInfo> {
    this.startupFailure = undefined
    this.startupStage = undefined
    this.startupStageElapsedMs = undefined
    this.startupStartedAt = undefined
    this.startupLastProgressAt = undefined
    this.error = undefined
    this.transition('starting')
    const developmentMode = this.options.runtimeMode === 'desktop-development'
      && (this.options.environment?.NETCONSOLE_DEV_MODE ?? process.env.NETCONSOLE_DEV_MODE) === '1'
    const configuredToken = developmentMode
      ? (this.options.environment?.NETCONSOLE_DEV_SESSION_TOKEN ?? process.env.NETCONSOLE_DEV_SESSION_TOKEN)
      : undefined
    const apiToken = configuredToken || this.options.createToken()
    if (!/^[A-Za-z0-9_-]{32,256}$/.test(apiToken)) {
      throw new Error('Python backend token generator returned an invalid token')
    }
    const requestedPort = developmentMode
      ? parseDevelopmentPort(
        this.options.environment?.NETCONSOLE_DEV_BACKEND_PORT ?? process.env.NETCONSOLE_DEV_BACKEND_PORT,
      )
      : 0
    const args = [
      ...this.options.argumentsPrefix,
      '--host',
      '127.0.0.1',
      '--port',
      String(requestedPort),
      ...(this.options.rendererOrigin ? ['--renderer-origin', this.options.rendererOrigin] : []),
      ...(developmentMode ? ['--dev-mode'] : []),
    ]
    const environment: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.options.environment,
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
      NETCONSOLE_DATA_ROOT: this.options.dataRoot,
      NETCONSOLE_STORAGE_MODE: this.options.storageMode ?? 'persistent',
      ...(this.options.activeSiteId ? { NETCONSOLE_ACTIVE_SITE_ID: this.options.activeSiteId } : {}),
      NETCONSOLE_RUNTIME_MODE: this.options.storageMode === 'isolated_test' ? 'test' : this.options.runtimeMode,
    }
    if (this.options.pythonPath) {
      const existingPythonPath = this.options.environment?.PYTHONPATH ?? process.env.PYTHONPATH
      environment.PYTHONPATH = existingPythonPath
        ? `${this.options.pythonPath}${delimiter}${existingPythonPath}`
        : this.options.pythonPath
    } else {
      delete environment.PYTHONPATH
    }
    if (!this.options.activeSiteId) delete environment.NETCONSOLE_ACTIVE_SITE_ID
    delete environment.NETCONSOLE_DEV_SESSION_TOKEN

    let child: ManagedChildProcess | undefined
    try {
      const spawnedAt = Date.now()
      this.startupStartedAt = spawnedAt
      this.startupLastProgressAt = spawnedAt
      child = this.options.spawnProcess(this.options.executable, args, {
        cwd: this.options.projectRoot,
        env: environment,
        shell: false,
        windowsHide: true,
        stdio: 'pipe',
      })
      this.options.onStartupMilestone?.('backend.spawn_started')
      this.child = child
      this.attachProcessHandlers(child, apiToken)
      const runtimeAnnouncement = this.waitForRuntimeAnnouncement(child, apiToken, requestedPort, spawnedAt)
      child.stdin.write(`${JSON.stringify({ session_token: apiToken })}\n`, 'utf8')
      const runtime = await runtimeAnnouncement
      this.options.onStartupMilestone?.('backend.handshake_received')
      this.runtime = runtime
      await this.pollUntilReady(child, runtime)
      this.options.onStartupMilestone?.('backend.health_ready')
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
    requestedPort: number,
    spawnedAt: number,
  ): Promise<BackendRuntimeInfo> {
    return new Promise((resolvePromise, reject) => {
      let settled = false
      let firstStdoutSeen = false
      const timeout = setInterval(() => {
        const timeoutError = this.currentStartupTimeoutError()
        if (timeoutError) finish(timeoutError)
      }, Math.max(10, Math.min(this.options.pollIntervalMs, 250)))
      const onError = (cause: Error) => finish(cause)
      const onExit = (code: number | null, signal: NodeJS.Signals | null) => finish(
        new Error(`Python backend exited before port handshake (code=${code ?? 'none'}, signal=${signal ?? 'none'})`),
      )
      const finish = (cause?: Error, runtime?: BackendRuntimeInfo): void => {
        if (settled) return
        settled = true
        clearInterval(timeout)
        child.removeListener('error', onError)
        child.removeListener('exit', onExit)
        if (cause) reject(cause)
        else resolvePromise(runtime!)
      }
      child.once('error', onError)
      child.once('exit', onExit)
      attachLineLogger(child.stdout, 'stdout', apiToken, this.options.logger, (line) => {
        if (!firstStdoutSeen) {
          firstStdoutSeen = true
          this.options.logger(
            'ELECTRON_BACKEND_FIRST_STDOUT',
            `pid=${child.pid ?? 'none'} elapsed_ms=${Date.now() - spawnedAt}`,
          )
        }
        let payload: unknown
        try {
          payload = JSON.parse(line)
        } catch {
          return
        }
        const event = payloadEvent(payload)
        if (event === 'netconsole.electron_backend.startup_stage') {
          if (isStartupStage(payload)) {
            this.startupStage = payload.stage
            this.startupStageElapsedMs = payload.elapsed_ms
            this.startupLastProgressAt = Date.now()
            this.options.onStartupProgress?.({
              stage: payload.stage,
              elapsedMs: payload.elapsed_ms,
              ...(Number.isInteger(child.pid) && (child.pid ?? 0) > 0 ? { pid: child.pid } : {}),
            })
          }
          return
        }
        if (isStartupFailure(payload)) {
          const failure = new Error(payload.message)
          this.startupFailure = failure
          finish(failure)
          return
        }
        if (event === 'netconsole.electron_backend.shutdown_received') {
          this.shutdownReceived.add(child)
          for (const listener of this.shutdownReceivedListeners) listener(child)
          return
        }
        if (event === 'netconsole.electron_backend.shutdown_complete') {
          this.shutdownComplete.add(child)
          for (const listener of this.shutdownCompleteListeners) listener(child)
          return
        }
        if (event === 'netconsole.electron_backend.shutdown_ack') {
          // Compatibility with older packaged backends. New runtimes emit the
          // two explicit lifecycle events above.
          this.shutdownReceived.add(child)
          this.shutdownComplete.add(child)
          for (const listener of this.shutdownReceivedListeners) listener(child)
          for (const listener of this.shutdownCompleteListeners) listener(child)
          return
        }
        if (settled) return
        if (!isRuntimeAnnouncement(payload)) return
        if (requestedPort && payload.port !== requestedPort) {
          finish(new Error('Python backend announced an unexpected fixed development port'))
          return
        }
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
    while (true) {
      if (this.stopRequested) throw new Error('Python backend startup was cancelled')
      if (this.startupFailure) throw this.startupFailure
      const timeoutError = this.currentStartupTimeoutError()
      if (timeoutError) throw timeoutError
      if (this.child !== child || child.exitCode !== null) {
        throw new Error('Python backend exited before becoming ready')
      }
      const controller = new AbortController()
      const remainingHardDeadline = this.options.startupHardTimeoutMs - (
        Date.now() - (this.startupStartedAt ?? Date.now())
      )
      const requestTimeoutMs = Math.max(
        1,
        Math.min(1_000, this.options.pollIntervalMs * 5, remainingHardDeadline),
      )
      const timeout = setTimeout(() => controller.abort(), requestTimeoutMs)
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
      this.options.logger(
        'ELECTRON_BACKEND_PROCESS_EXITED',
        `pid=${child.pid ?? 'none'} code=${code ?? 'none'} signal=${signal ?? 'none'}`,
      )
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
      await this.escalateTermination(child)
      return
    }
    let receivedListener!: (value: ManagedChildProcess) => void
    const received = new Promise<boolean>((resolvePromise) => {
      if (this.shutdownReceived.has(child)) {
        resolvePromise(true)
        return
      }
      receivedListener = (value) => {
        if (value === child) resolvePromise(true)
      }
      this.shutdownReceivedListeners.add(receivedListener)
    })
    try {
      child.stdin.write(`${JSON.stringify({ command: 'shutdown' })}\n`, 'utf8')
      this.options.logger('ELECTRON_BACKEND_SHUTDOWN_SENT')
    } catch {
      this.shutdownReceivedListeners.delete(receivedListener)
      await this.escalateTermination(child)
      return
    }
    const acknowledged = await this.waitForSignal(received)
    this.shutdownReceivedListeners.delete(receivedListener)
    if (!acknowledged) {
      this.options.logger('ELECTRON_BACKEND_SHUTDOWN_RECEIVED_TIMEOUT')
      await this.escalateTermination(child)
      return
    }
    this.options.logger('ELECTRON_BACKEND_SHUTDOWN_ACKNOWLEDGED')
    let completeListener!: (value: ManagedChildProcess) => void
    const complete = new Promise<boolean>((resolvePromise) => {
      if (this.shutdownComplete.has(child)) {
        resolvePromise(true)
        return
      }
      completeListener = (value) => {
        if (value === child) resolvePromise(true)
      }
      this.shutdownCompleteListeners.add(completeListener)
    })
    const shutdownComplete = await this.waitForSignal(complete)
    this.shutdownCompleteListeners.delete(completeListener)
    if (!shutdownComplete) {
      this.options.logger('ELECTRON_BACKEND_SHUTDOWN_COMPLETE_TIMEOUT')
      await this.escalateTermination(child)
      return
    }
    this.options.logger('ELECTRON_BACKEND_SHUTDOWN_COMPLETE')
    try {
      child.stdin.write(`${JSON.stringify({ command: 'exit' })}\n`, 'utf8')
    } catch {
      // stdin may already be closed after the runtime completed its shutdown.
    }
    child.stdin.end()
    this.options.logger('ELECTRON_BACKEND_CONTROL_CLOSED')
    if (!(await this.waitForProcessExitWithin(child, this.options.stopTimeoutMs))) {
      await this.escalateTermination(child)
    }
    this.options.logger('ELECTRON_BACKEND_PROCESS_RELEASED')
  }

  private async waitForSignal(signal: Promise<boolean>): Promise<boolean> {
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<boolean>((resolvePromise) => {
      timer = setTimeout(() => resolvePromise(false), this.options.stopTimeoutMs)
    })
    try {
      return await Promise.race([signal, timeout])
    } finally {
      if (timer) clearTimeout(timer)
    }
  }

  private async waitForProcessExitWithin(child: ManagedChildProcess, timeoutMs: number): Promise<boolean> {
    if (child.exitCode !== null) return true
    const exited = this.waitForProcessExit(child).then(() => true)
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<boolean>((resolvePromise) => {
      timer = setTimeout(() => resolvePromise(false), timeoutMs)
    })
    try {
      return await Promise.race([exited, timeout])
    } finally {
      if (timer) clearTimeout(timer)
    }
  }

  private async escalateTermination(child: ManagedChildProcess): Promise<void> {
    child.stdin.end()
    this.options.logger('ELECTRON_BACKEND_TERMINATE_REQUESTED')
    child.kill('SIGTERM')
    if (await this.waitForProcessExitWithin(child, this.options.stopTimeoutMs)) return
    child.kill('SIGKILL')
    if (await this.waitForProcessExitWithin(child, this.options.stopTimeoutMs)) return
    const pid = child.pid
    if (process.platform === 'win32' && typeof pid === 'number' && Number.isInteger(pid) && pid > 0) {
      const terminated = await this.options.forceTerminateProcessTree(pid)
      if (terminated && await this.waitForProcessExitWithin(child, this.options.stopTimeoutMs)) return
    }
    throw new Error('Python backend did not exit after termination escalation')
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

  private startupTimeoutMessage(reason: string): string {
    const stage = this.startupStage ?? 'before first startup stage'
    const elapsed = this.startupStageElapsedMs == null ? 'unknown' : `${this.startupStageElapsedMs}ms`
    return `Python backend startup timed out (${reason}); last_stage=${stage}; last_stage_elapsed=${elapsed}`
  }

  private currentStartupTimeoutError(now = Date.now()): Error | undefined {
    const startedAt = this.startupStartedAt ?? now
    if (now - startedAt >= this.options.startupHardTimeoutMs) {
      return new Error(this.startupTimeoutMessage('hard deadline'))
    }
    const lastProgressAt = this.startupLastProgressAt ?? startedAt
    if (now - lastProgressAt >= this.options.startupTimeoutMs) {
      return new Error(this.startupTimeoutMessage('stage watchdog'))
    }
    return undefined
  }
}

function parseDevelopmentPort(value: string | undefined): number {
  if (!value) return 0
  const port = Number(value)
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('NETCONSOLE_DEV_BACKEND_PORT must be between 1 and 65535')
  }
  return port
}

function defaultSpawn(
  command: string,
  args: string[],
  options: SpawnOptionsWithoutStdio,
): ManagedChildProcess {
  return spawnChild(command, args, options) as ManagedChildProcess
}

function defaultForceTerminateProcessTree(pid: number): Promise<boolean> {
  return new Promise((resolvePromise) => {
    const taskkill = spawnChild('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
      shell: false,
      windowsHide: true,
      stdio: 'ignore',
    })
    const finish = (value: boolean): void => resolvePromise(value)
    taskkill.once('error', () => finish(false))
    taskkill.once('exit', (code) => finish(code === 0 || code === 128))
  })
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
      logBackendOutput(source, line, secret, logger)
    }
  })
  stream.on('end', () => {
    if (pending) onLine?.(pending)
    logBackendOutput(source, pending, secret, logger)
  })
}

function logBackendOutput(
  source: string,
  line: string,
  secret: string,
  logger: DesktopLogger,
): void {
  const safe = redactSensitiveText(line, [secret])
  if (!safe) return
  if (source === 'stdout') {
    let event = ''
    try {
      const payload = JSON.parse(safe) as { event?: unknown }
      event = typeof payload.event === 'string' ? payload.event : ''
    } catch {
      // Non-JSON stdout is useful only in explicitly enabled development logging.
    }
    const lifecycleEvents = new Set([
      'netconsole.electron_backend.startup_stage',
      'netconsole.electron_backend.listening',
      'netconsole.electron_backend.startup_failed',
      'netconsole.electron_backend.shutdown_received',
      'netconsole.electron_backend.shutdown_complete',
    ])
    logger('ELECTRON_BACKEND_STDOUT', event ? `event=${event}` : safe, lifecycleEvents.has(event) ? 'INFO' : 'DEBUG')
    return
  }
  const level = /^LOG_WRITE_RECOVERED\b/.test(safe)
    ? 'INFO'
    : /(?:^|\s)(?:ERROR|CRITICAL|Traceback|Exception|Error:)/i.test(safe)
      ? 'ERROR'
      : 'WARNING'
  logger('ELECTRON_BACKEND_STDERR', safe, level)
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

function isStartupFailure(value: unknown): value is {
  event: 'netconsole.electron_backend.startup_failed'
  message: string
} {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const payload = value as Record<string, unknown>
  return payload.event === 'netconsole.electron_backend.startup_failed'
    && typeof payload.message === 'string'
    && payload.message.trim().length > 0
}

function payloadEvent(value: unknown): string {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    && typeof (value as Record<string, unknown>).event === 'string'
    ? String((value as Record<string, unknown>).event)
    : ''
}

function isStartupStage(value: unknown): value is { stage: string; elapsed_ms: number } {
  return payloadEvent(value) === 'netconsole.electron_backend.startup_stage'
    && typeof (value as Record<string, unknown>).stage === 'string'
    && typeof (value as Record<string, unknown>).elapsed_ms === 'number'
}
