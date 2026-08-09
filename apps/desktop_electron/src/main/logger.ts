import { appendFile, mkdir, readdir, rename, stat, unlink } from 'node:fs/promises'
import { dirname, join } from 'node:path'

import { DESKTOP_LOG_POLICY } from './log-policy'

export type DesktopLogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
export type DesktopLogger = (event: string, detail?: string, level?: DesktopLogLevel) => void

export interface ManagedDesktopLogger extends DesktopLogger {
  flush: () => Promise<void>
}

export interface FileLoggerOptions {
  minimumLevel?: DesktopLogLevel
  now?: () => Date
  maxFileBytes?: number
  renameFile?: typeof rename
}

const SENSITIVE_VALUE_RE = /((?:session[_-]?token|api[_-]?token|agent[_-]?token|authorization|password|passphrase|private[_-]?key|ssh[_-]?key|community|secret)\s*["']?\s*[:=]\s*["']?)(?:Bearer\s+)?[^\s,"'};]+/gi
const ROTATED_LOG_RE = /^electron-(\d{8})-\d{6}-(\d{4})\.log$/

interface DuplicateState {
  count: number
  lastSeenAt: number
  lastSummaryAt: number
}

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
  const previewBytes = Math.max(0, maxBytes - 80)
  const preview = Buffer.from(safe, 'utf8').subarray(0, previewBytes).toString('utf8')
  return `${preview} payload_truncated=true original_bytes=${originalBytes}`
}

export function createFileLogger(
  logPath: string,
  options: FileLoggerOptions = {},
): ManagedDesktopLogger {
  let writeChain = Promise.resolve()
  const duplicateStates = new Map<string, DuplicateState>()
  const minimumLevel = options.minimumLevel ?? configuredMinimumLevel()

  const logger = ((event: string, detail = '', level: DesktopLogLevel = 'INFO'): void => {
    if (!shouldWriteLevel(level, minimumLevel)) return
    const safeEvent = redactSensitiveText(event).toUpperCase().replace(/[^A-Z0-9_.-]/g, '_')
    const safeDetail = truncateApplicationDetail(detail)
    const timestamp = options.now?.() ?? new Date()
    const now = timestamp.getTime()
    const fingerprint = `${level}|${safeEvent}|${normalizeFingerprint(safeDetail)}`
    const state = duplicateStates.get(fingerprint)
    let outputDetail = safeDetail
    if (state) {
      const gap = now - state.lastSeenAt
      state.lastSeenAt = now
      state.count += 1
      if (gap <= DESKTOP_LOG_POLICY.duplicateSuppression.windowMs) {
        if (now - state.lastSummaryAt < DESKTOP_LOG_POLICY.duplicateSuppression.summaryIntervalMs) return
        outputDetail = `${safeDetail} repeated=${state.count} window_ms=${now - state.lastSummaryAt}`
        state.count = 0
        state.lastSummaryAt = now
      } else {
        state.count = 0
        state.lastSummaryAt = now
      }
    } else {
      pruneDuplicateStates(duplicateStates, now)
      duplicateStates.set(fingerprint, { count: 0, lastSeenAt: now, lastSummaryAt: now })
    }
    const line = `${timestamp.toISOString()} | ${level} | ${safeEvent} | ${truncateApplicationDetail(outputDetail)}\n`
    writeChain = writeChain.then(async () => {
      await mkdir(dirname(logPath), { recursive: true })
      await rotateIfNeeded(
        logPath,
        timestamp,
        Buffer.byteLength(line, 'utf8'),
        options.maxFileBytes ?? DESKTOP_LOG_POLICY.electron.maxFileBytes,
        options.renameFile ?? rename,
      )
      await appendFile(logPath, line, { encoding: 'utf8' })
    }).catch((cause) => {
      void writeRotationFallback(logPath, safeEvent, cause)
    })
  }) as ManagedDesktopLogger
  logger.flush = () => writeChain
  return logger
}

async function rotateIfNeeded(
  path: string,
  now: Date,
  incomingBytes: number,
  maxFileBytes: number,
  renameFile: typeof rename,
): Promise<void> {
  let current
  try {
    current = await stat(path)
  } catch (cause) {
    if (isMissing(cause)) return
    throw cause
  }
  if (current.size + incomingBytes <= maxFileBytes && sameLocalDay(current.mtime, now)) return
  const date = formatLocalDate(now)
  const time = formatLocalTime(now)
  const sequence = await nextSequence(dirname(path), date)
  const rotated = join(dirname(path), `electron-${date}-${time}-${String(sequence).padStart(4, '0')}.log`)
  try {
    await renameFile(path, rotated)
    await pruneElectronLogs(dirname(path), now)
  } catch (cause) {
    await writeRotationFallback(path, 'ELECTRON_LOG_ROTATION_FAILED', cause)
  }
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

async function writeRotationFallback(path: string, event: string, cause: unknown): Promise<void> {
  const fallback = join(dirname(path), 'electron-log-fallback.log')
  const message = `${new Date().toISOString()} | ERROR | ${event} | error_type=${cause instanceof Error ? cause.name : 'unknown'}\n`
  await appendFile(fallback, message, { encoding: 'utf8' }).catch(() => {
    try { process.stderr.write(message) } catch { /* best effort only */ }
  })
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
