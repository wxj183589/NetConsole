import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { cleanupIsolatedRuntime, createIsolatedRuntime, discoverProjectPython } from './dev-runtime.mjs'

const roots = []
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })

describe('Electron development runtime isolation', () => {
  it('creates one isolated root with data, runtime, and Electron userData', () => {
    const temp = mkdtempSync(join(tmpdir(), 'netconsole-dev-runtime-test-'))
    roots.push(temp)
    const runtime = createIsolatedRuntime(temp)
    expect(existsSync(runtime.dataRoot)).toBe(true)
    expect(existsSync(runtime.runtimeRoot)).toBe(true)
    expect(existsSync(runtime.userDataRoot)).toBe(true)
    cleanupIsolatedRuntime(runtime.root, temp)
    expect(existsSync(runtime.root)).toBe(false)
  })

  it('fails Python discovery without creating or changing storage', () => {
    const log = vi.fn()
    expect(() => discoverProjectPython({ projectRoot: 'C:\\missing', environment: {}, platform: 'win32', probe: false, log }))
      .toThrow('未找到项目 Python 运行时')
    expect(log).toHaveBeenCalledWith('ELECTRON_PYTHON_DISCOVERY_FAILED')
  })
})
