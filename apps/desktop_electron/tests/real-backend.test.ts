import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { PythonBackendManager } from '../src/main/backend-manager'
import { DESKTOP_SESSION_HEADER } from '../src/shared/bridge'
import type { NetConsoleDesktopBridge } from '../src/shared/bridge'
import { getHealth } from '../../web/src/api/client'
import {
  initializePlatformRuntime,
  resetPlatformRuntimeForTests,
} from '../../web/src/platform/runtime'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const cleanupDirectories: string[] = []

afterEach(async () => {
  resetPlatformRuntimeForTests()
  vi.unstubAllGlobals()
  await Promise.all(cleanupDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})

describe('real Python backend integration', () => {
  it('starts the existing FastAPI app, serves authenticated health, and exits through the control pipe', async () => {
    const dataRoot = await mkdtemp(resolve(tmpdir(), 'netconsole-electron-test-'))
    cleanupDirectories.push(dataRoot)
    const logs: string[] = []
    const manager = new PythonBackendManager({
      executable: findProjectPython(),
      argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      projectRoot,
      startupTimeoutMs: 15_000,
      stopTimeoutMs: 8_000,
      environment: {
        NETCONSOLE_DATA_ROOT: dataRoot,
        ONLINE_MR_WEB_CONTROL_ENABLED: '0',
        ONLINE_MR_AGENT_EXECUTOR_ENABLED: '0',
      },
      logger: (event, detail) => logs.push(`${event} ${detail ?? ''}`),
    })

    try {
      const runtime = await manager.start()
      const unauthorized = await fetch(`${runtime.baseUrl}/api/health`)
      const authorized = await fetch(`${runtime.baseUrl}/api/health`, {
        headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
      })

      expect(unauthorized.status).toBe(401)
      expect(authorized.status).toBe(200)
      await expect(authorized.json()).resolves.toMatchObject({ status: 'ok' })
      vi.stubGlobal('window', {
        netconsoleDesktop: runtimeBridge(runtime.baseUrl, runtime.apiToken),
        location: { origin: 'http://127.0.0.1:5173', protocol: 'http:', host: '127.0.0.1:5173' },
      })
      await initializePlatformRuntime()
      await expect(getHealth()).resolves.toMatchObject({ status: 'ok' })
      expect(logs.join('\n')).not.toContain(runtime.apiToken)
    } finally {
      await manager.stop()
    }

    expect(manager.getStatus()).toEqual({ state: 'stopped' })
  })
})

function runtimeBridge(apiBaseUrl: string, apiToken: string): NetConsoleDesktopBridge {
  return {
    getAppInfo: vi.fn(async () => ({ version: '1.3.8', platform: 'win32', isPackaged: false })),
    getBackendStatus: vi.fn(async () => ({ state: 'ready' as const, baseUrl: apiBaseUrl })),
    getRuntimeConfig: vi.fn(async () => ({ apiBaseUrl, apiToken })),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
    onBackendStatusChanged: vi.fn(() => () => undefined),
    reportRendererReady: vi.fn(),
  }
}

function findProjectPython(): string {
  if (process.env.NETCONSOLE_PYTHON && existsSync(process.env.NETCONSOLE_PYTHON)) {
    return process.env.NETCONSOLE_PYTHON
  }
  const relative = process.platform === 'win32'
    ? ['.venv', 'Scripts', 'python.exe']
    : ['.venv', 'bin', 'python']
  const candidates = [resolve(projectRoot, ...relative)]
  try {
    const commonGitDir = execFileSync(
      'git',
      ['-C', projectRoot, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { encoding: 'utf8' },
    ).trim()
    candidates.push(resolve(commonGitDir, '..', ...relative))
  } catch {
    // 由下面的明确错误报告缺失运行时。
  }
  const python = candidates.find(existsSync)
  if (!python) throw new Error(`未找到项目虚拟环境 Python：${candidates.join(', ')}`)
  return python
}
