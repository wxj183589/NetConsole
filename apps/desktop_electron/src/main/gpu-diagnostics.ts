import type { DesktopLogger } from './logger'

export interface ChildProcessGoneDiagnostic {
  event: 'ELECTRON_GPU_PROCESS_GONE' | 'ELECTRON_UTILITY_PROCESS_GONE' | 'ELECTRON_CHILD_PROCESS_GONE'
  detail: string
}

export function logDevelopmentGpuFeatureStatus(
  enabled: boolean,
  readStatus: () => Record<string, string>,
  logger: DesktopLogger,
): void {
  if (!enabled) return
  try {
    const status = readStatus()
    const detail = Object.entries(status)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([feature, value]) => `${feature}=${value}`)
      .join(' ')
    logger('ELECTRON_GPU_FEATURE_STATUS', detail || 'unavailable')
  } catch {
    logger('ELECTRON_GPU_FEATURE_STATUS', 'unavailable')
  }
}

export function buildChildProcessGoneDiagnostic(details: {
  type?: unknown
  reason?: unknown
  exitCode?: unknown
  serviceName?: unknown
}): ChildProcessGoneDiagnostic {
  const type = safeChildProcessField(details.type)
  const reason = safeChildProcessField(details.reason)
  const exitCode = Number.isSafeInteger(details.exitCode) ? details.exitCode : -1
  const serviceName = safeChildProcessField(details.serviceName)
  const event = type.toLowerCase() === 'gpu'
    ? 'ELECTRON_GPU_PROCESS_GONE'
    : type.toLowerCase() === 'utility'
      ? 'ELECTRON_UTILITY_PROCESS_GONE'
      : 'ELECTRON_CHILD_PROCESS_GONE'
  return {
    event,
    detail: `type=${type} reason=${reason} exit_code=${exitCode} service_name=${serviceName}`,
  }
}

function safeChildProcessField(value: unknown): string {
  const text = typeof value === 'string' ? value : 'unknown'
  return /^[A-Za-z0-9_. -]{1,80}$/.test(text) ? text.replace(/\s+/g, '_') : 'unknown'
}
