const REQUIRED_SCENARIOS = Object.freeze(['missing', 'stale'])

const REQUIRED_ELECTRON_LOG_MARKERS = Object.freeze([
  'ELECTRON_BACKEND_READY',
  'ELECTRON_BACKEND_STARTUP_STAGE stage=active_site_database_initializing',
  'ELECTRON_BACKEND_STARTUP_STAGE stage=active_site_database_ready',
  'ELECTRON_BACKEND_STARTUP_STAGE stage=ap_identity_index_initializing',
  'ELECTRON_BACKEND_STARTUP_STAGE stage=ap_identity_index_ready',
  'ELECTRON_STARTUP_TIMELINE event=backend.health_ready',
  'ELECTRON_STARTUP_TIMELINE event=renderer.mounted',
  'ELECTRON_STARTUP_TIMELINE event=desktop.interactive',
  'ELECTRON_MAIN_WINDOW_STARTUP_SMOKE_PASSED',
  'ELECTRON_SMOKE_RENDERER_READY phase=interactive health_ok=true',
  'STARTUP_PERFORMANCE_SUMMARY',
  'ELECTRON_SMOKE_RENDERER_STABLE',
])

const REQUIRED_BACKEND_LOG_MARKERS = Object.freeze([
  'DATA_ROOT_CONTEXT',
  'environment=PRODUCTION',
  'PRODUCTION_DATA_ROOT_ACTIVE',
])

const FORBIDDEN_LOG_MARKERS = Object.freeze([
  'ELECTRON_BACKEND_START_FAILED',
  'startup_failed',
  'ELECTRON_MAIN_WINDOW_STARTUP_SMOKE_FAILED',
  'ELECTRON_SMOKE_WATCHDOG_EXPIRED',
  'ELECTRON_RENDERER_NAVIGATION_REJECTED',
])

export function parsePackageApIdentityStartupSmoke(rawValue) {
  const value = String(rawValue ?? '').trim().toLowerCase()
  if (!value || value === '0' || value === 'off') return []
  if (value === 'both') return [...REQUIRED_SCENARIOS]
  if (REQUIRED_SCENARIOS.includes(value)) return [value]
  throw new Error(
    `NETCONSOLE_PACKAGE_AP_IDENTITY_STARTUP_SMOKE 仅允许 missing/stale/both，当前为：${value}`,
  )
}

export function assertProductionApIdentityStartupSmokeLogs({
  scenario,
  exitCode,
  electronLog,
  backendLog,
}) {
  if (!REQUIRED_SCENARIOS.includes(scenario)) {
    throw new Error(`未知 AP Identity startup smoke 场景：${scenario}`)
  }
  if (exitCode !== 0) {
    throw new Error(`AP Identity ${scenario} packaged smoke exit code=${exitCode}`)
  }
  const electronText = String(electronLog ?? '')
  const backendText = String(backendLog ?? '')
  const allText = `${electronText}\n${backendText}`
  const missingElectronMarkers = REQUIRED_ELECTRON_LOG_MARKERS.filter(
    (marker) => !electronText.includes(marker),
  )
  if (missingElectronMarkers.length > 0) {
    throw new Error(
      `AP Identity ${scenario} Electron smoke log missing: ${missingElectronMarkers.join(', ')}`,
    )
  }
  const missingBackendMarkers = REQUIRED_BACKEND_LOG_MARKERS.filter(
    (marker) => !backendText.includes(marker),
  )
  if (missingBackendMarkers.length > 0) {
    throw new Error(
      `AP Identity ${scenario} Backend log missing: ${missingBackendMarkers.join(', ')}`,
    )
  }
  const forbidden = FORBIDDEN_LOG_MARKERS.filter((marker) => allText.includes(marker))
  if (forbidden.length > 0) {
    throw new Error(
      `AP Identity ${scenario} packaged smoke log contains failure markers: ${forbidden.join(', ')}`,
    )
  }
  return true
}

export const packageApIdentityStartupSmokeScenarios = REQUIRED_SCENARIOS
