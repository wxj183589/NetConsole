// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TaskItem } from '../types/task'

const mocks = vi.hoisted(() => ({
  chooseSavePath: vi.fn(),
  downloadBackendResource: vi.fn(),
  getActiveSite: vi.fn(),
  getTask: vi.fn(),
  getPlatformAdapter: vi.fn(),
}))

vi.mock('../api/siteStorage', () => ({
  getActiveSite: mocks.getActiveSite,
}))

vi.mock('../platform/runtime', () => ({
  downloadBackendResource: mocks.downloadBackendResource,
  getPlatformAdapter: mocks.getPlatformAdapter,
}))

vi.mock('../api/tasks', () => ({
  getTask: mocks.getTask,
}))

import {
  bindingForTask,
  resetUserSelectedExportForTests,
  retryArtifactSave,
  saveReadyArtifact,
  startExportSaveCoordinator,
  stopExportSaveCoordinator,
  submitExportAfterDestinationSelected,
} from './useUserSelectedExport'

const SHA256 = 'a'.repeat(64)

function artifact(name = '设备表.csv'): NonNullable<TaskItem['artifact_download']> {
  return {
    artifact_id: 'artifact-1',
    display_name: name,
    size_bytes: 128,
    sha256: SHA256,
    media_type: 'text/csv',
    api_path: '/api/device-management/exports/task-1/download',
    query: { artifact_id: 'artifact-1' },
  }
}

function electronAdapter() {
  return {
    hostType: 'electron',
    chooseSavePath: mocks.chooseSavePath,
  }
}

beforeEach(() => {
  resetUserSelectedExportForTests()
  vi.clearAllMocks()
  mocks.getPlatformAdapter.mockReturnValue(electronAdapter())
  mocks.getActiveSite.mockResolvedValue({
    site_id: 'site-a',
    display_name: '测试局点',
  })
  mocks.chooseSavePath.mockResolvedValue({
    cancelled: false,
    path: 'D:\\operator\\测试局点-设备表.csv',
  })
  mocks.downloadBackendResource.mockResolvedValue({
    status: 'saved',
    fileName: '测试局点-设备表.csv',
    directoryLabel: 'D:\\operator',
    capabilityId: 'capability-1',
  })
  mocks.getTask.mockRejectedValue(new Error('not ready'))
})

describe('useUserSelectedExport', () => {
  it('does not submit an export when Save As is cancelled', async () => {
    mocks.chooseSavePath.mockResolvedValueOnce({ cancelled: true })
    const submit = vi.fn()

    const result = await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '设备表.csv',
      submit,
    })

    expect(result).toEqual({ status: 'cancelled' })
    expect(submit).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toBeNull()
  })

  it('adds the current site display name to the desktop Save As suggestion', async () => {
    await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '设备表.csv',
      submit: vi.fn().mockResolvedValue({ task_id: 'task-1' }),
    })

    expect(mocks.chooseSavePath).toHaveBeenCalledWith({
      suggestedName: '测试局点-设备表.csv',
      filters: [{ name: 'CSV 文件', extensions: ['csv'] }],
    })
    expect(bindingForTask('task-1')?.fileName).toBe('测试局点-设备表.csv')
  })

  it('does not duplicate the current site prefix when the page already supplies it', async () => {
    mocks.chooseSavePath.mockResolvedValueOnce({
      cancelled: false,
      path: 'D:\\operator\\测试局点-设备表.csv',
    })

    await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '测试局点-设备表.csv',
      submit: vi.fn().mockResolvedValue({ task_id: 'task-1' }),
    })

    expect(mocks.chooseSavePath).toHaveBeenCalledWith(expect.objectContaining({
      suggestedName: '测试局点-设备表.csv',
    }))
  })

  it('binds the authorized target before saving once without a second dialog', async () => {
    const submit = vi.fn().mockResolvedValue({ task_id: 'task-1' })
    const submitted = await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '设备表.csv',
      context: { scope: 'filtered_all', requestedRowCount: 3 },
      submit,
    })

    expect(submitted.status).toBe('submitted')
    expect(submit).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem('netconsole.user-selected-exports.v1')).toContain('task-1')

    await saveReadyArtifact('task-1', artifact())

    expect(mocks.chooseSavePath).toHaveBeenCalledOnce()
    expect(mocks.downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/device-management/exports/task-1/download',
      query: { artifact_id: 'artifact-1' },
      suggestedName: '测试局点-设备表.csv',
      destinationPath: 'D:\\operator\\测试局点-设备表.csv',
      expectedSizeBytes: 128,
      expectedSha256: SHA256,
    })
    expect(bindingForTask('task-1')?.state).toBe('saved')
  })

  it('retains the Artifact after a save failure and retries without another export task', async () => {
    const submit = vi.fn().mockResolvedValue({ task_id: 'task-1' })
    await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '设备表.csv',
      submit,
    })
    mocks.downloadBackendResource.mockResolvedValueOnce({
      status: 'failed',
      error: 'access denied',
    })

    await saveReadyArtifact('task-1', artifact())

    expect(bindingForTask('task-1')?.state).toBe('save_failed')
    expect(bindingForTask('task-1')?.artifact?.artifact_id).toBe('artifact-1')

    mocks.chooseSavePath.mockResolvedValueOnce({
      cancelled: false,
      path: 'E:\\retry\\设备表.csv',
    })
    const saved = await retryArtifactSave('task-1')

    expect(saved).toBe(true)
    expect(submit).toHaveBeenCalledOnce()
    expect(mocks.chooseSavePath).toHaveBeenCalledTimes(2)
    expect(mocks.downloadBackendResource).toHaveBeenLastCalledWith(expect.objectContaining({
      destinationPath: 'E:\\retry\\设备表.csv',
      expectedSizeBytes: 128,
      expectedSha256: SHA256,
    }))
  })

  it('uses browser download only in browser mode and does not claim a verified save', async () => {
    mocks.getPlatformAdapter.mockReturnValue({
      hostType: 'browser',
      chooseSavePath: mocks.chooseSavePath,
    })
    mocks.downloadBackendResource.mockResolvedValueOnce({ status: 'started' })
    await submitExportAfterDestinationSelected({
      action: 'devices.csv',
      suggestedName: '设备表.csv',
      submit: vi.fn().mockResolvedValue({ task_id: 'task-browser' }),
    })

    await saveReadyArtifact('task-browser', artifact())

    expect(mocks.chooseSavePath).not.toHaveBeenCalled()
    expect(mocks.downloadBackendResource).toHaveBeenCalledWith(expect.not.objectContaining({
      destinationPath: expect.anything(),
    }))
    expect(bindingForTask('task-browser')?.state).toBe('browser_started')
    expect(mocks.getActiveSite).not.toHaveBeenCalled()
  })

  it('restores only explicitly bound tasks and never prompts for unrelated history', async () => {
    sessionStorage.setItem('netconsole.user-selected-exports.v1', JSON.stringify([{
      taskId: 'task-restored',
      action: 'devices.csv',
      destinationMode: 'electron',
      destinationPath: 'D:\\operator\\restored.csv',
      suggestedName: 'restored.csv',
      fileName: 'restored.csv',
      directoryLabel: 'D:\\operator',
      state: 'task_running',
      context: {},
    }]))
    mocks.getTask.mockResolvedValue({
      id: 'task-restored',
      status: 'PENDING',
      artifact_download: null,
    })

    startExportSaveCoordinator()
    await vi.waitFor(() => expect(mocks.getTask).toHaveBeenCalledWith('task-restored'))
    stopExportSaveCoordinator()

    expect(bindingForTask('task-restored')?.destinationPath).toBe('D:\\operator\\restored.csv')
    expect(mocks.chooseSavePath).not.toHaveBeenCalled()
    expect(mocks.downloadBackendResource).not.toHaveBeenCalled()
  })
})
