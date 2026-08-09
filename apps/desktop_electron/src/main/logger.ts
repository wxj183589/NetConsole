import { appendFile, mkdir, readdir, rename, stat, unlink, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

import { DESKTOP_LOG_POLICY } from './log-policy'

export type DesktopLogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
export type DesktopLogger = (event: string, detail?: string, level?: DesktopLogLevel) => void

export interface LogQueueMetrics {
  queuedEvents: number
  queuedBytes: number
  peakQueuedBytes: number
  droppedDebug: number
  droppedInfo: number
  droppedWarning: number
  droppedError: number
  backpressureActive: boolean
}

export interface ManagedDesktopLogger extends DesktopLogger {
  flush: (timeoutMs?: number) => Promise<void>
  getQueueMetrics: () => LogQueueMetrics
}

type AppendLine = (path: string, line: string) => Promise<void>

export interface FileLoggerOptions {
  minimumLevel?: DesktopLogLevel
  now?: () => Date
  maxFileBytes?: number
  renameFile?: typeof rename
  appendLine?: AppendLine
  queueSoftLimitBytes?: number
  queueHardLimitBytes?: number
  flushTimeoutMs?: number
  fallbackMaxBytes?: number
}

interface DuplicateState {
  count: number
  lastSeenAt: number
  lastSummaryAt: number
}

interface QueuedLogEntry {
  line: string
  bytes: number
  level: DesktopLogLevel
}

interface DroppedCounts {
  debug: number
  info: number
  warning: number
  error: number
}

interface BackpressureIncident {
  startedAt: number
  lastSummaryAt: number
  summaryEmitted: boolean
  peakQueuedBytes: number
  dropped: DroppedCounts
}

interface RotationFailureState {
  consecutiveFailures: number
  nextRetryAt: number
  lastFailureAt: number
  firstFailureAt: number
}

interface FallbackFingerprintState {
  count: number
  lastSummaryAt: number
}

const SENSITIVE_VALUE_RE = /((?:session[_-]?token|api[_-]?token|agent[_-]?token|authorization|password|passphrase|private[_-]?key|ssh[_-]?key|community|secret)\s*["']?\s*[:=]\s*["']?)(?:Bearer\s+)?[^\s,"'};]+/gi
const ROTATED_LOG_RE = /^electron-(\d{8})-\d{6}-(\d{4})\.log$/
const FALLBACK_SUMMARY_INTERVAL_MS = 60_000

export function redactSensitiveText(value: unknown, secrets: readonly string[] = []): string {
  let safe = String(value ?? '').replace(/[\r\n]+/g, ' ').trim()
  for (const secret of secrets) {
    if (secret) safe = safe.split(secret).join('***')
  }
  return safe.replace(SENSITIVE_VALUE_RE, '$1***')
}

export function truncateApplicationDetail(value: unknown, maxBytes = DESKTOP_LOG_POLICY.applicationLog.maxEventBytes): string {
  const safe = redactSensitiveText(value)
  const originalBytes = Buffer.byteLength(safe, 'utf8')
  if (originalBytes <= maxBytes) return safe
  const marker = ` payload_truncated=true original_bytes=${originalBytes}`
  const previewBytes = Math.max(0, maxBytes - Buffer.byteLength(marker, 'utf8'))
  const preview = Buffer.from(safe, 'utf8').subarray(0, previewBytes).toString('utf8').replace(/\uFFFD$/, '')
  return `${preview}${marker}`
}

export function createFileLogger(
  logPath: string,
  options: FileLoggerOptions = {},
): ManagedDesktopLogger {
  const queue: QueuedLogEntry[] = []
  const duplicateStates = new Map<string, DuplicateState>()
  const minimumLevel = options.minimumLevel ?? configuredMinimumLevel()
  const now = options.now ?? (() => new Date())
  const appendLine = options.appendLine ?? appendUtf8
  const softLimit = options.queueSoftLimitBytes ?? DESKTOP_LOG_POLICY.electron.queueSoftLimitBytes
  const hardLimit = options.queueHardLimitBytes ?? DESKTOP_LOG_POLICY.electron.queueHardLimitBytes
  const flushTimeoutMs = options.flushTimeoutMs ?? DESKTOP_LOG_POLICY.electron.flushTimeoutMs
  const rotationState: RotationFailureState = {
    consecutiveFailures: 0,
    nextRetryAt: 0,
    lastFailureAt: 0,
    firstFailureAt: 0,
  }
  const fallback = createFallbackReporter(
    logPath,
    now,
    options.fallbackMaxBytes ?? DESKTOP_LOG_POLICY.electron.fallbackMaxBytes,
  )
  const dropped: DroppedCounts = emptyDroppedCounts()
  let queuedBytes = 0
  let peakQueuedBytes = 0
  let draining = false
  let incident: BackpressureIncident | undefined
  let idleWaiters: Array<() => void> = []

  if (softLimit >= hardLimit) throw new Error('Electron log queue soft limit must be below hard limit')

  const markDropped = (level: DesktopLogLevel, timestamp: number): void => {
    incrementDropped(dropped, level)
    if (!incident) {
      incident = {
        startedAt: timestamp,
        lastSummaryAt: 0,
        summaryEmitted: false,
        peakQueuedBytes: queuedBytes,
        dropped: emptyDroppedCounts(),
      }
    }
    incrementDropped(incident.dropped, level)
  }

  const updatePressurePeak = (): void => {
    peakQueuedBytes = Math.max(peakQueuedBytes, queuedBytes)
    if (incident) incident.peakQueuedBytes = Math.max(incident.peakQueuedBytes, queuedBytes)
  }

  const removeQueuedEntry = (index: number, timestamp: number): void => {
    const [removed] = queue.splice(index, 1)
    if (!removed) return
    queuedBytes = Math.max(0, queuedBytes - removed.bytes)
    markDropped(removed.level, timestamp)
  }

  const makeRoomForPriorityEntry = (requiredBytes: number, timestamp: number): void => {
    for (let index = queue.length - 1; index >= (draining ? 1 : 0); index -= 1) {
      if (queuedBytes + requiredBytes <= hardLimit) return
      if (queue[index]?.level === 'DEBUG' || queue[index]?.level === 'INFO') {
        removeQueuedEntry(index, timestamp)
      }
    }
  }

  const persistLine = async (line: string): Promise<void> => {
    await mkdir(dirname(logPath), { recursive: true })
    const rotationRecovery = await rotateIfNeeded(
      logPath,
      now(),
      Buffer.byteLength(line, 'utf8'),
      options.maxFileBytes ?? DESKTOP_LOG_POLICY.electron.maxFileBytes,
      options.renameFile ?? rename,
      rotationState,
      fallback,
    )
    if (rotationRecovery) {
      await appendLine(logPath, formatLine(now(), 'INFO', 'ELECTRON_LOG_ROTATION_RECOVERED', rotationRecovery))
    }
    await appendLine(logPath, line)
  }

  const persistControlEvent = async (event: string, detail: string, level: DesktopLogLevel): Promise<void> => {
    try {
      await persistLine(formatLine(now(), level, event, detail))
    } catch (cause) {
      await fallback('ELECTRON_LOG_WRITE_FAILED', cause)
    }
  }

  const maybeWriteBackpressureSummary = async (): Promise<void> => {
    if (!incident) return
    const timestamp = now().getTime()
    if (
      incident.summaryEmitted
      && timestamp - incident.lastSummaryAt < DESKTOP_LOG_POLICY.duplicateSuppression.summaryIntervalMs
    ) return
    incident.summaryEmitted = true
    incident.lastSummaryAt = timestamp
    await persistControlEvent(
      'LOG_BACKPRESSURE',
      pressureDetail(queuedBytes, incident.peakQueuedBytes, incident.dropped),
      'WARNING',
    )
  }

  const finishBackpressureIncident = async (): Promise<void> => {
    if (!incident) return
    await maybeWriteBackpressureSummary()
    const finished = incident
    await persistControlEvent(
      'LOG_BACKPRESSURE_RECOVERED',
      `duration_ms=${Math.max(0, now().getTime() - finished.startedAt)} ${pressureDetail(queuedBytes, finished.peakQueuedBytes, finished.dropped)}`,
      'INFO',
    )
    incident = undefined
  }

  const notifyIdle = (): void => {
    if (draining || queue.length > 0) return
    const waiters = idleWaiters
    idleWaiters = []
    for (const resolvePromise of waiters) resolvePromise()
  }

  const drainQueue = async (): Promise<void> => {
    try {
      while (queue.length > 0) {
        await maybeWriteBackpressureSummary()
        const entry = queue[0]!
        try {
          await persistLine(entry.line)
        } catch (cause) {
          await fallback('ELECTRON_LOG_WRITE_FAILED', cause)
        } finally {
          if (queue[0] === entry) queue.shift()
          else {
            const index = queue.indexOf(entry)
            if (index >= 0) queue.splice(index, 1)
          }
          queuedBytes = Math.max(0, queuedBytes - entry.bytes)
        }
      }
      await finishBackpressureIncident()
    } finally {
      draining = false
      if (queue.length > 0) scheduleDrain()
      else notifyIdle()
    }
  }

  const scheduleDrain = (): void => {
    if (draining) return
    draining = true
    void drainQueue()
  }

  const logger = ((event: string, detail = '', level: DesktopLogLevel = 'INFO'): void => {
    if (!shouldWriteLevel(level, minimumLevel)) return
    const safeEvent = redactSensitiveText(event).toUpperCase().replace(/[^A-Z0-9_.-]/g, '_')
    const safeDetail = truncateApplicationDetail(detail)
    const timestamp = now()
    const timestampMs = timestamp.getTime()
    const fingerprint = `${level}|${safeEvent}|${normalizeFingerprint(safeDetail)}`
    const state = duplicateStates.get(fingerprint)
    let outputDetail = safeDetail
    if (state) {
      const gap = timestampMs - state.lastSeenAt
      state.lastSeenAt = timestampMs
      state.count += 1
      if (gap <= DESKTOP_LOG_POLICY.duplicateSuppression.windowMs) {
        if (timestampMs - state.lastSummaryAt < DESKTOP_LOG_POLICY.duplicateSuppression.summaryIntervalMs) return
        outputDetail = `${safeDetail} repeated=${state.count} window_ms=${timestampMs - state.lastSummaryAt}`
        state.count = 0
        state.lastSummaryAt = timestampMs
      } else {
        state.count = 0
        state.lastSummaryAt = timestampMs
      }
    } else {
      pruneDuplicateStates(duplicateStates, timestampMs)
      duplicateStates.set(fingerprint, { count: 0, lastSeenAt: timestampMs, lastSummaryAt: timestampMs })
    }

    const line = formatLine(timestamp, level, safeEvent, outputDetail)
    const entry: QueuedLogEntry = { line, bytes: Buffer.byteLength(line, 'utf8'), level }
    if (queuedBytes + entry.bytes > softLimit && (level === 'DEBUG' || level === 'INFO')) {
      markDropped(level, timestampMs)
      scheduleDrain()
      return
    }
    if (queuedBytes + entry.bytes > hardLimit) makeRoomForPriorityEntry(entry.bytes, timestampMs)
    if (queuedBytes + entry.bytes > hardLimit) {
      markDropped(level, timestampMs)
      scheduleDrain()
      return
    }
    queue.push(entry)
    queuedBytes += entry.bytes
    updatePressurePeak()
    scheduleDrain()
  }) as ManagedDesktopLogger

  logger.getQueueMetrics = () => ({
    queuedEvents: queue.length,
    queuedBytes,
    peakQueuedBytes,
    droppedDebug: dropped.debug,
    droppedInfo: dropped.info,
    droppedWarning: dropped.warning,
    droppedError: dropped.error,
    backpressureActive: incident !== undefined,
  })
  logger.flush = async (timeoutOverride?: number): Promise<void> => {
    if (!draining && queue.length === 0) return
    const idle = new Promise<void>((resolvePromise) => idleWaiters.push(resolvePromise))
    const timeout = Math.max(1, timeoutOverride ?? flushTimeoutMs)
    let timer: ReturnType<typeof setTimeout> | undefined
    await Promise.race([
      idle,
      new Promise<void>((resolvePromise) => {
        timer = setTimeout(resolvePromise, timeout)
      }),
    ])
    if (timer) clearTimeout(timer)
  }
  return logger
}

async function rotateIfNeeded(
  path: string,
  now: Date,
  incomingBytes: number,
  maxFileBytes: number,
  renameFile: typeof rename,
  failureState: RotationFailureState,
  fallback: (event: string, cause: unknown) => Promise<void>,
): Promise<string> {
  let current
  try {
    current = await stat(path)
  } catch (cause) {
    if (isMissing(cause)) return ''
    throw cause
  }
  if (current.size + incomingBytes <= maxFileBytes && sameLocalDay(current.mtime, now)) return ''
  if (now.getTime() < failureState.nextRetryAt) return ''
  const date = formatLocalDate(now)
  const time = formatLocalTime(now)
  const sequence = await nextSequence(dirname(path), date)
  const rotated = join(dirname(path), `electron-${date}-${time}-${String(sequence).padStart(4, '0')}.log`)
  try {
    await renameFile(path, rotated)
    await pruneElectronLogs(dirname(path), now)
    if (failureState.consecutiveFailures === 0) return ''
    const detail = [
      `failures=${failureState.consecutiveFailures}`,
      `duration_ms=${Math.max(0, now.getTime() - failureState.firstFailureAt)}`,
    ].join(' ')
    resetRotationFailureState(failureState)
    return detail
  } catch (cause) {
    const timestamp = now.getTime()
    failureState.consecutiveFailures += 1
    failureState.firstFailureAt ||= timestamp
    failureState.lastFailureAt = timestamp
    const delays = DESKTOP_LOG_POLICY.electron.rotationRetryMs
    failureState.nextRetryAt = timestamp + delays[Math.min(failureState.consecutiveFailures - 1, delays.length - 1)]!
    await fallback('ELECTRON_LOG_ROTATION_FAILED', cause)
    return ''
  }
}

function createFallbackReporter(
  logPath: string,
  now: () => Date,
  maxBytes: number,
): (event: string, cause: unknown) => Promise<void> {
  const states = new Map<string, FallbackFingerprintState>()
  const stderrStates = new Map<string, FallbackFingerprintState>()
  const fallbackPath = join(dirname(logPath), 'electron-log-fallback.log')
  return async (event: string, cause: unknown): Promise<void> => {
    const timestamp = now()
    const errorType = cause instanceof Error ? cause.name : 'unknown'
    const code = errorCode(cause)
    const fingerprint = `${event}|${errorType}|${code}|${normalizeFingerprint(cause instanceof Error ? cause.message : String(cause))}`
    const state = states.get(fingerprint)
    let repeated = 0
    if (state) {
      state.count += 1
      if (timestamp.getTime() - state.lastSummaryAt < FALLBACK_SUMMARY_INTERVAL_MS) return
      repeated = state.count
      state.count = 0
      state.lastSummaryAt = timestamp.getTime()
    } else {
      pruneFallbackStates(states, timestamp.getTime())
      states.set(fingerprint, { count: 0, lastSummaryAt: timestamp.getTime() })
    }
    const detail = `error_type=${errorType} code=${code}${repeated ? ` repeated=${repeated}` : ''}`
    const message = formatLine(timestamp, 'ERROR', event, detail)
    try {
      await mkdir(dirname(fallbackPath), { recursive: true })
      let currentBytes = 0
      try {
        currentBytes = (await stat(fallbackPath)).size
      } catch (statCause) {
        if (!isMissing(statCause)) throw statCause
      }
      if (currentBytes + Buffer.byteLength(message, 'utf8') > maxBytes) {
        await writeFile(fallbackPath, message, { encoding: 'utf8' })
      } else {
        await appendFile(fallbackPath, message, { encoding: 'utf8' })
      }
    } catch (fallbackCause) {
      writeFallbackStderr(stderrStates, timestamp, event, fallbackCause)
    }
  }
}

function writeFallbackStderr(
  states: Map<string, FallbackFingerprintState>,
  timestamp: Date,
  event: string,
  cause: unknown,
): void {
  try {
    const fingerprint = `${event}|${cause instanceof Error ? cause.name : 'unknown'}|${errorCode(cause)}`
    const state = states.get(fingerprint)
    let repeated = 0
    if (state) {
      state.count += 1
      if (timestamp.getTime() - state.lastSummaryAt < FALLBACK_SUMMARY_INTERVAL_MS) return
      repeated = state.count
      state.count = 0
      state.lastSummaryAt = timestamp.getTime()
    } else {
      pruneFallbackStates(states, timestamp.getTime())
      states.set(fingerprint, { count: 0, lastSummaryAt: timestamp.getTime() })
    }
    const detail = truncateApplicationDetail(
      `fallback_write_failed=true error_type=${cause instanceof Error ? cause.name : 'unknown'} code=${errorCode(cause)}${repeated ? ` repeated=${repeated}` : ''}`,
    )
    process.stderr.write(formatLine(timestamp, 'ERROR', event, detail))
  } catch {
    // Final best-effort diagnostic path must never escape to the application.
  }
}

async function appendUtf8(path: string, line: string): Promise<void> {
  await appendFile(path, line, { encoding: 'utf8' })
}

function formatLine(timestamp: Date, level: DesktopLogLevel, event: string, detail: string): string {
  return `${timestamp.toISOString()} | ${level} | ${event} | ${truncateApplicationDetail(detail)}\n`
}

function pressureDetail(queuedBytes: number, peak: number, dropped: DroppedCounts): string {
  return [
    `queued_bytes=${queuedBytes}`,
    `peak_queued_bytes=${peak}`,
    `dropped_debug=${dropped.debug}`,
    `dropped_info=${dropped.info}`,
    `dropped_warning=${dropped.warning}`,
    `dropped_error=${dropped.error}`,
  ].join(' ')
}

function emptyDroppedCounts(): DroppedCounts {
  return { debug: 0, info: 0, warning: 0, error: 0 }
}

function incrementDropped(counts: DroppedCounts, level: DesktopLogLevel): void {
  if (level === 'DEBUG') counts.debug += 1
  else if (level === 'INFO') counts.info += 1
  else if (level === 'WARNING') counts.warning += 1
  else counts.error += 1
}

function resetRotationFailureState(state: RotationFailureState): void {
  state.consecutiveFailures = 0
  state.nextRetryAt = 0
  state.lastFailureAt = 0
  state.firstFailureAt = 0
}

async function nextSequence(directory: string, date: string): Promise<number> {
  try {
    const names = await readdir(directory)
    const values = names.flatMap((name) => {
      const match = ROTATED_LOG_RE.exec(name)
      return match?.[1] === date ? [Number(match[2])] : []
    })
    return Math.max(0, ...values) + 1
  } catch {
    return 1
  }
}

async function pruneElectronLogs(directory: string, now: Date): Promise<void> {
  const cutoff = now.getTime() - DESKTOP_LOG_POLICY.electron.retentionDays * 86_400_000
  let names: string[]
  try {
    names = await readdir(directory)
  } catch {
    return
  }
  await Promise.all(names.filter((name) => ROTATED_LOG_RE.test(name)).map(async (name) => {
    const path = join(directory, name)
    try {
      if ((await stat(path)).mtimeMs < cutoff) await unlink(path)
    } catch {
      // Housekeeper will retry deletion without impacting the active logger.
    }
  }))
}

function normalizeFingerprint(value: string): string {
  return value
    .replace(/\b\d{4,}\b/g, '{n}')
    .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, '{uuid}')
    .replace(/\s+/g, ' ')
}

function pruneDuplicateStates(states: Map<string, DuplicateState>, now: number): void {
  if (states.size < 4_096) return
  const cutoff = now - DESKTOP_LOG_POLICY.duplicateSuppression.summaryIntervalMs * 2
  for (const [fingerprint, state] of states) {
    if (state.lastSeenAt < cutoff) states.delete(fingerprint)
  }
  if (states.size < 8_192) return
  const oldest = [...states.entries()]
    .sort((left, right) => left[1].lastSeenAt - right[1].lastSeenAt)
    .slice(0, states.size - 4_096)
  for (const [fingerprint] of oldest) states.delete(fingerprint)
}

function pruneFallbackStates(states: Map<string, FallbackFingerprintState>, now: number): void {
  if (states.size < 256) return
  const cutoff = now - FALLBACK_SUMMARY_INTERVAL_MS * 2
  for (const [fingerprint, state] of states) {
    if (state.lastSummaryAt < cutoff) states.delete(fingerprint)
  }
  while (states.size > 256) states.delete(states.keys().next().value as string)
}

function sameLocalDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

function formatLocalDate(value: Date): string {
  return `${value.getFullYear()}${String(value.getMonth() + 1).padStart(2, '0')}${String(value.getDate()).padStart(2, '0')}`
}

function formatLocalTime(value: Date): string {
  return `${String(value.getHours()).padStart(2, '0')}${String(value.getMinutes()).padStart(2, '0')}${String(value.getSeconds()).padStart(2, '0')}`
}

function errorCode(cause: unknown): string {
  if (!cause || typeof cause !== 'object') return 'unknown'
  if ('code' in cause && cause.code != null) return redactSensitiveText(cause.code)
  if ('errno' in cause && cause.errno != null) return redactSensitiveText(cause.errno)
  return 'unknown'
}

function isMissing(cause: unknown): boolean {
  return Boolean(cause && typeof cause === 'object' && 'code' in cause && cause.code === 'ENOENT')
}

function configuredMinimumLevel(): DesktopLogLevel {
  const configured = String(process.env.NETCONSOLE_LOG_LEVEL ?? '').trim().toUpperCase()
  return configured === 'DEBUG' ? 'DEBUG' : 'INFO'
}

function shouldWriteLevel(level: DesktopLogLevel, minimum: DesktopLogLevel): boolean {
  if (minimum === 'DEBUG') return true
  return level !== 'DEBUG'
}
