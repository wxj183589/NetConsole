import { appendFile, mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'

export type DesktopLogger = (event: string, detail?: string) => void

const SENSITIVE_VALUE_RE = /((?:session[_-]?token|api[_-]?token|agent[_-]?token|authorization|password|passphrase|private[_-]?key|ssh[_-]?key|community|secret)\s*["']?\s*[:=]\s*["']?)(?:Bearer\s+)?[^\s,"'};]+/gi

export function redactSensitiveText(value: unknown, secrets: readonly string[] = []): string {
  let safe = String(value ?? '').replace(/[\r\n]+/g, ' ').trim()
  for (const secret of secrets) {
    if (secret) safe = safe.split(secret).join('***')
  }
  return safe.replace(SENSITIVE_VALUE_RE, '$1***')
}

export function createFileLogger(logPath: string): DesktopLogger {
  let writeChain = Promise.resolve()
  return (event, detail = '') => {
    const safeEvent = redactSensitiveText(event).toUpperCase().replace(/[^A-Z0-9_.-]/g, '_')
    const safeDetail = redactSensitiveText(detail)
    const line = `${new Date().toISOString()} | ${safeEvent} | ${safeDetail}\n`
    writeChain = writeChain
      .then(async () => {
        await mkdir(dirname(logPath), { recursive: true })
        await appendFile(logPath, line, { encoding: 'utf8' })
      })
      .catch(() => undefined)
  }
}
