import policyDocument from '../../../../src/netconsole/resources/log_policy.json'

export interface DesktopLogPolicy {
  applicationLog: {
    maxEventBytes: number
    productionLevel: 'INFO'
    developmentLevel: 'DEBUG'
  }
  electron: {
    maxFileBytes: number
    retentionDays: number
    queueSoftLimitBytes: number
    queueHardLimitBytes: number
    flushTimeoutMs: number
    fallbackMaxBytes: number
    rotationRetryMs: readonly number[]
  }
  duplicateSuppression: {
    windowMs: number
    summaryIntervalMs: number
  }
}

function positiveInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) {
    throw new Error(`Invalid log policy value: ${name}`)
  }
  return Number(value)
}

export function loadDesktopLogPolicy(): DesktopLogPolicy {
  if (policyDocument.schema_version !== 1) throw new Error('Unsupported log policy schema')
  return {
    applicationLog: {
      maxEventBytes: positiveInteger(policyDocument.application_log.max_event_bytes, 'max_event_bytes'),
      productionLevel: 'INFO',
      developmentLevel: 'DEBUG',
    },
    electron: {
      maxFileBytes: positiveInteger(policyDocument.electron.max_file_bytes, 'electron.max_file_bytes'),
      retentionDays: positiveInteger(policyDocument.electron.retention_days, 'electron.retention_days'),
      queueSoftLimitBytes: positiveInteger(policyDocument.electron.queue_soft_limit_bytes, 'electron.queue_soft_limit_bytes'),
      queueHardLimitBytes: positiveInteger(policyDocument.electron.queue_hard_limit_bytes, 'electron.queue_hard_limit_bytes'),
      flushTimeoutMs: positiveInteger(policyDocument.electron.flush_timeout_ms, 'electron.flush_timeout_ms'),
      fallbackMaxBytes: positiveInteger(policyDocument.electron.fallback_max_bytes, 'electron.fallback_max_bytes'),
      rotationRetryMs: policyDocument.electron.rotation_retry_seconds.map((value, index) => (
        positiveInteger(value, `electron.rotation_retry_seconds[${index}]`) * 1_000
      )),
    },
    duplicateSuppression: {
      windowMs: positiveInteger(policyDocument.duplicate_suppression.window_seconds, 'window_seconds') * 1_000,
      summaryIntervalMs: positiveInteger(policyDocument.duplicate_suppression.summary_interval_seconds, 'summary_interval_seconds') * 1_000,
    },
  }
}

export const DESKTOP_LOG_POLICY = loadDesktopLogPolicy()
