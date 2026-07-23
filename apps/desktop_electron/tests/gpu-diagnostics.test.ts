import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it, vi } from 'vitest'

import {
  buildChildProcessGoneDiagnostic,
  logDevelopmentGpuFeatureStatus,
} from '../src/main/gpu-diagnostics'

describe('Electron GPU diagnostics', () => {
  it('logs only feature states in development mode', () => {
    const logger = vi.fn()
    logDevelopmentGpuFeatureStatus(true, () => ({
      gpu_compositing: 'enabled',
      webgl: 'software_only',
    }), logger)
    expect(logger).toHaveBeenCalledWith(
      'ELECTRON_GPU_FEATURE_STATUS',
      'gpu_compositing=enabled webgl=software_only',
    )
  })

  it('does not block startup when GPU status is unavailable', () => {
    const logger = vi.fn()
    expect(() => logDevelopmentGpuFeatureStatus(true, () => {
      throw new Error('unavailable')
    }, logger)).not.toThrow()
    expect(logger).toHaveBeenCalledWith('ELECTRON_GPU_FEATURE_STATUS', 'unavailable')
  })

  it('keeps Chromium hardware acceleration and software fallback defaults intact', () => {
    const source = readFileSync(fileURLToPath(new URL('../src/main/index.ts', import.meta.url)), 'utf8')
    expect(source).not.toContain('disableHardwareAcceleration')
    expect(source).not.toContain('--disable-gpu')
    expect(source).not.toContain('--disable-gpu-compositing')
  })

  it('records GPU and Network Service exits separately from Renderer exits', () => {
    expect(buildChildProcessGoneDiagnostic({
      type: 'GPU',
      reason: 'crashed',
      exitCode: 34,
    })).toEqual({
      event: 'ELECTRON_GPU_PROCESS_GONE',
      detail: 'type=GPU reason=crashed exit_code=34 service_name=unknown',
    })
    expect(buildChildProcessGoneDiagnostic({
      type: 'Utility',
      reason: 'killed',
      exitCode: 15,
      serviceName: 'network.mojom.NetworkService',
    })).toEqual({
      event: 'ELECTRON_UTILITY_PROCESS_GONE',
      detail: 'type=Utility reason=killed exit_code=15 service_name=network.mojom.NetworkService',
    })
    const source = readFileSync(fileURLToPath(new URL('../src/main/index.ts', import.meta.url)), 'utf8')
    expect(source).toContain("app.on('child-process-gone'")
    expect(source).not.toContain("logger('ELECTRON_RENDERER_PROCESS_GONE'")
  })
})
