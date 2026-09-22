import { describe, expect, it } from 'vitest'

import {
  assertProductionApIdentityStartupSmokeLogs,
  parsePackageApIdentityStartupSmoke,
} from '../scripts/package-smoke-ap-identity.js'

const electronLog = [
  'ELECTRON_BACKEND_READY',
  'ELECTRON_BACKEND_STARTUP_STAGE | stage=active_site_database_initializing',
  'ELECTRON_BACKEND_STARTUP_STAGE | stage=active_site_database_ready',
  'ELECTRON_BACKEND_STARTUP_STAGE | stage=ap_identity_index_initializing',
  'ELECTRON_BACKEND_STARTUP_STAGE | stage=ap_identity_index_ready',
  'ELECTRON_STARTUP_TIMELINE | event=backend.health_ready',
  'ELECTRON_STARTUP_TIMELINE | event=renderer.mounted',
  'ELECTRON_STARTUP_TIMELINE | event=desktop.interactive',
  'ELECTRON_MAIN_WINDOW_STARTUP_SMOKE_PASSED',
  'ELECTRON_SMOKE_RENDERER_READY | phase=interactive health_ok=true',
  'STARTUP_PERFORMANCE_SUMMARY',
  'ELECTRON_SMOKE_RENDERER_STABLE',
].join('\n')

const backendLog = [
  'DATA_ROOT_CONTEXT data_root=C:\\test-data environment=PRODUCTION',
  'PRODUCTION_DATA_ROOT_ACTIVE',
].join('\n')

describe('package AP Identity startup smoke contract', () => {
  it('accepts the opt-in scenarios and keeps the default disabled', () => {
    expect(parsePackageApIdentityStartupSmoke(undefined)).toEqual([])
    expect(parsePackageApIdentityStartupSmoke('both')).toEqual(['missing', 'stale'])
    expect(() => parsePackageApIdentityStartupSmoke('unknown')).toThrow()
  })

  it('requires successful packaged startup logs without failure markers', () => {
    expect(assertProductionApIdentityStartupSmokeLogs({
      scenario: 'missing',
      exitCode: 0,
      electronLog,
      backendLog,
    })).toBe(true)
    expect(() => assertProductionApIdentityStartupSmokeLogs({
      scenario: 'stale',
      exitCode: 0,
      electronLog: `${electronLog}\nELECTRON_BACKEND_START_FAILED`,
      backendLog,
    })).toThrow()
  })

  it('does not accept detail markers without the logger separator', () => {
    const legacyElectronLog = electronLog.replaceAll(' | ', ' ')
    expect(() => assertProductionApIdentityStartupSmokeLogs({
      scenario: 'missing',
      exitCode: 0,
      electronLog: legacyElectronLog,
      backendLog,
    })).toThrow(/Electron smoke log missing/)
  })
})
