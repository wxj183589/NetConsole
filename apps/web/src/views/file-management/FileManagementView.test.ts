import { describe, expect, it, vi } from 'vitest'

import {
  clearFileDownloads,
  connectDeviceFiles,
  createLocalDirectory,
  listLocalFiles,
  prepareFileDesktopAction,
  retryFileDownload,
  startRemoteFileDownloadBatch,
} from '../../api/fileManagement'
import source from './FileManagementView.vue?raw'

describe('file management API contract', () => {
  it('uses opaque dual-pane references and one batch request', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], tasks: [], failures: [] }) })
    vi.stubGlobal('fetch', fetchMock)

    await listLocalFiles({ site_id: 'demo', directory_id: 'fl1_opaque', device_id: 'device-1', page: 2, limit: 200 })
    await createLocalDirectory({ site_id: 'demo', directory_id: 'fl1_opaque', device_id: 'device-1', name: 'logs' })
    await startRemoteFileDownloadBatch('fc1_session', ['fe1_a', 'fe1_b'], 'demo', 'fl1_opaque')

    expect(fetchMock.mock.calls[0][0]).toContain('directory_id=fl1_opaque')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ directory_id: 'fl1_opaque', device_id: 'device-1', name: 'logs' })
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      connection_id: 'fc1_session',
      remote_entry_ids: ['fe1_a', 'fe1_b'],
      local_directory_id: 'fl1_opaque',
    })
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain('remote_path')
  })

  it('sends explicit SFTP setup consent and persistent queue actions', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await connectDeviceFiles('device-1', 'demo', true)
    await retryFileDownload('task-1', 'demo')
    await clearFileDownloads(['COMPLETED', 'FAILED'], 'demo')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ device_id: 'device-1', allow_sftp_setup: true })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/file-management/downloads/task-1/retry?site_id=demo')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ statuses: ['COMPLETED', 'FAILED'] })
  })

  it('prepares a typed desktop action without argv, path or password', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ action_ref: 'fda1_opaque' }) })
    vi.stubGlobal('fetch', fetchMock)

    await prepareFileDesktopAction('winscp', { site_id: 'demo', device_id: 'device-1' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/file-management/desktop-actions/winscp?site_id=demo')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({ device_id: 'device-1' })
    expect(JSON.stringify(body)).not.toMatch(/password|argv|path/i)
  })

  it('requires one in-session confirmation before allowing controlled SFTP setup', () => {
    expect(source).toContain('SFTP 未启用时，允许自动配置并重连')
    expect(source).toContain('@change="confirmSftpSetup"')
    expect(source).toContain('const sftpSetupConfirmed = ref(false)')
    expect(source).toContain('if (accepted) sftpSetupConfirmed.value = true')
    expect(source).toContain('else allowSftpSetup.value = false')
    expect(source).not.toContain('localStorage.setItem(\'netconsole.file-management.sftp')
  })

  it('maps stable SFTP setup errors and exposes an existing task id', () => {
    for (const code of [
      'DEVICE_FILE_SFTP_UNAVAILABLE',
      'DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED',
      'DEVICE_FILE_SFTP_ENABLE_PENDING',
      'DEVICE_FILE_SFTP_ENABLE_FAILED',
      'DEVICE_FILE_SFTP_ENABLE_SUCCEEDED_BUT_RECONNECT_FAILED',
    ]) expect(source).toContain(code)
    expect(source).toContain('reason.details.task_id')
    expect(source).toContain('openTaskWindow(sftpSetupTaskId)')
    expect(source).toContain('const SFTP_SETUP_SUCCESS_MESSAGE = \'已在设备侧启用 SFTP，并完成重新连接。\'')
    expect(source).toContain('ElMessage.success(connection.value.message)')
  })
})
