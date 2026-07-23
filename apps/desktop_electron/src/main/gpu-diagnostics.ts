import type { DesktopLogger } from './logger'

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
