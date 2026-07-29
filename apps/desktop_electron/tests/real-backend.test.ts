import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { PythonBackendManager } from '../src/main/backend-manager'
import { BackendDownloadManager } from '../src/main/backend-download'
import { GrantedPathRegistry } from '../src/main/path-access'
import { DESKTOP_SESSION_HEADER } from '../src/shared/bridge'
import type { NetConsoleDesktopBridge } from '../src/shared/bridge'
import { getHealth } from '../../web/src/api/client'
import { listDevices } from '../../web/src/api/deviceManagement'
import {
  fileDownloadRequest,
  getFileDownloadTask,
  getFileManagementStatus,
  listManagedFiles,
  startFileDownload,
} from '../../web/src/api/fileManagement'
import { stationTemplateDownloadRequest } from '../../web/src/api/railTransitBaseData'
import {
  initializePlatformRuntime,
  resetPlatformRuntimeForTests,
  resolveWebSocketUrl,
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
    const configuredTestRoot = process.env.NETCONSOLE_DATA_ROOT?.trim()
    if (!configuredTestRoot) throw new Error('NETCONSOLE_DATA_ROOT is required for the real backend test')
    const dataRoot = await mkdtemp(resolve(dirname(configuredTestRoot), 'netconsole-electron-test-'))
    cleanupDirectories.push(dataRoot)
    const logs: string[] = []
    const sourcePath = resolve(
      dataRoot,
      'sites',
      'demo',
      'files',
      'rail_transit',
      'online_mr',
      'MR-1',
      'sessions',
      'session-1',
      'outputs',
      'dynamic-port-test.zip',
    )
    await mkdir(dirname(sourcePath), { recursive: true })
    await writeFile(sourcePath, 'dynamic-port-download', 'utf8')
    const manager = new PythonBackendManager({
      executable: findProjectPython(),
      argumentsPrefix: ['-m', 'netconsole.backend.electron_runtime'],
      projectRoot,
      dataRoot,
      runtimeMode: 'desktop-development',
      storageMode: 'isolated_test',
      pythonPath: resolve(projectRoot, 'src'),
      startupTimeoutMs: 15_000,
      stopTimeoutMs: 8_000,
      environment: {
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
      expect(resolveWebSocketUrl('/ws/tasks')).toBe(
        runtime.baseUrl.replace(/^http:/, 'ws:') + '/ws/tasks',
      )
      await expect(listDevices({ page: 1, page_size: 1 })).resolves.toMatchObject({ page: 1 })
      await expect(getFileManagementStatus('demo')).resolves.toMatchObject({ site_id: 'demo' })
      const files = await listManagedFiles({ site_id: 'demo', limit: 50 })
      const source = files.items.find((item) => item.name === 'dynamic-port-test.zip')
      expect(source).toBeDefined()
      const task = await startFileDownload(source!.file_ref, 'demo')
      const completed = await waitForDownload(task.task_id)
      const savedPath = resolve(dataRoot, 'saved-dynamic-port-test.zip')
      const downloadManager = new BackendDownloadManager({
        backend: manager,
        dialog: { showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: savedPath })) },
        window: {},
        pathRegistry: new GrantedPathRegistry(),
      })
      await expect(downloadManager.download(fileDownloadRequest(
        completed.task_id,
        completed.site_id,
        completed.result!.name,
      ))).resolves.toMatchObject({ status: 'saved', capabilityId: expect.stringMatching(/^[0-9a-f-]{36}$/) })
      await expect(readFile(savedPath, 'utf8')).resolves.toBe('dynamic-port-download')

      const templatePath = resolve(dataRoot, '线路站点与区间基础资料模板.xlsx')
      const templateDownloadManager = new BackendDownloadManager({
        backend: manager,
        dialog: { showSaveDialog: vi.fn(async () => ({ canceled: false, filePath: templatePath })) },
        window: {},
        pathRegistry: new GrantedPathRegistry(),
      })
      await expect(templateDownloadManager.download(stationTemplateDownloadRequest())).resolves.toMatchObject({
        status: 'saved',
        capabilityId: expect.stringMatching(/^[0-9a-f-]{36}$/),
      })
      const sheetNames = JSON.parse(execFileSync(
        findProjectPython(),
        [
          '-c',
          'import json,sys; from openpyxl import load_workbook; wb=load_workbook(sys.argv[1], read_only=True); print(json.dumps(wb.sheetnames, ensure_ascii=True))',
          templatePath,
        ],
        { encoding: 'utf8' },
      )) as string[]
      expect(sheetNames).toEqual(['01_线路参数', '02_线路节点', '03_区间配置', '字段说明'])
      expect(new URL(runtime.baseUrl).port).not.toBe('8000')
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
    openTaskWindow: vi.fn(async () => ({ success: true })),
    showTaskNotification: vi.fn(async () => ({ success: true })),
    setTaskTrayStatus: vi.fn(),
    selectFile: vi.fn(async () => ({ cancelled: true, paths: [] })),
    selectDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsTool: vi.fn(async () => ({ cancelled: true })),
    selectSettingsDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSettingsColor: vi.fn(async () => ({ cancelled: true })),
    executeSettingsAction: vi.fn(async () => ({ success: true })),
    selectDataRootDirectory: vi.fn(async () => ({ cancelled: true })),
    selectSitePackage: vi.fn(async () => ({ cancelled: true })),
    selectSiteExportDestination: vi.fn(async () => ({ cancelled: true })),
    restartBackend: vi.fn(async () => ({ success: true })),
    chooseSavePath: vi.fn(async () => ({ cancelled: true })),
    downloadBackendResource: vi.fn(async () => ({ status: 'cancelled' as const })),
    executeFileDesktopAction: vi.fn(async () => ({ success: true })),
    listExternalTools: vi.fn(async () => ({ schema_version: 1 as const, categories: [], tools: [] })),
    selectExternalToolExecutable: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolWorkingDirectory: vi.fn(async () => ({ cancelled: true })),
    selectExternalToolIcon: vi.fn(async () => ({ cancelled: true })),
    createExternalTool: vi.fn(async () => ({ success: true })),
    updateExternalTool: vi.fn(async () => ({ success: true })),
    deleteExternalTool: vi.fn(async () => ({ success: true })),
    setExternalToolFavorite: vi.fn(async () => ({ success: true })),
    reorderExternalTools: vi.fn(async () => ({ success: true })),
    reorderExternalToolCategories: vi.fn(async () => ({ success: true })),
    createExternalToolCategory: vi.fn(async () => ({ success: true })),
    renameExternalToolCategory: vi.fn(async () => ({ success: true })),
    deleteExternalToolCategory: vi.fn(async () => ({ success: true })),
    launchExternalTool: vi.fn(async (toolId: string) => ({ success: true, toolId })),
    revealExternalTool: vi.fn(async (toolId: string) => ({ success: true, toolId })),
    refreshExternalToolStatuses: vi.fn(async () => ({ schema_version: 1 as const, categories: [], tools: [] })),
    openPath: vi.fn(async () => ({ success: true })),
    showItemInFolder: vi.fn(async () => ({ success: true })),
    openExternalUrl: vi.fn(async () => ({ success: true })),
    onBackendStatusChanged: vi.fn(() => () => undefined),
    reportRendererReady: vi.fn(),
  }
}

async function waitForDownload(taskId: string) {
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    const task = await getFileDownloadTask(taskId, 'demo')
    if (task.status === 'COMPLETED' && task.result) return task
    if (task.status === 'FAILED' || task.status === 'CANCELLED') {
      throw new Error(`file download task ended as ${task.status}`)
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100))
  }
  throw new Error('file download task did not complete')
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
