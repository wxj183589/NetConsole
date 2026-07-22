import { describe, expect, it, vi } from 'vitest'

import {
  clearFileDownloads,
  confirmDeviceSftpSetup,
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

  it('continues SFTP setup with an opaque confirmation and persistent queue actions', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await connectDeviceFiles('device-1', 'demo')
    await confirmDeviceSftpSetup('sf1_confirmation', 'demo')
    await retryFileDownload('task-1', 'demo')
    await clearFileDownloads(['COMPLETED', 'FAILED'], 'demo')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ device_id: 'device-1' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/file-management/connections/confirm-sftp-setup?site_id=demo')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ confirmation_id: 'sf1_confirmation' })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/file-management/downloads/task-1/retry?site_id=demo')
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({ statuses: ['COMPLETED', 'FAILED'] })
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

  it('asks once only after detecting disabled SFTP and continues the same connection flow', () => {
    expect(source).toContain('DEVICE_FILE_SFTP_UNAVAILABLE')
    expect(source).toContain('设备未启用 SFTP，NetConsole 将通过受控命令启用 SFTP并重新连接。')
    expect(source).toContain('confirmDeviceSftpSetup(confirmationId, siteId.value)')
    expect(source).toContain("connectionStatus.value = '正在启用设备 SFTP'")
    expect(source).toContain("connectionStatus.value = '正在重新连接 SFTP'")
    expect(source).not.toContain('allowSftpSetup')
    expect(source).not.toContain('sftpSetupConfirmed')
    expect(source).not.toContain('sftpSetupConfirmationPending')
    expect(source).not.toContain('SFTP 未启用时，允许自动配置并重连')
  })

  it('keeps MESH as a selection shortcut and downloads only selected rows', () => {
    expect(source).toContain('@click="selectAllRemote(true)"')
    expect(source).toContain('await downloadRemoteEntries(remoteSelected.value)')
    expect(source).toContain('rows.map((row) => row.entry_id)')
    expect(source).not.toContain('downloadAndImportMesh')
    expect(source).not.toContain('downloadMeshLogsAndImport')
    expect(source).toContain('rebuild_required')
    expect(source).toContain('meshImportStatusText(row.result.mesh_import_status)')
  })

  it('maps stable SFTP/session errors and exposes an existing task id', () => {
    for (const code of [
      'DEVICE_FILE_NETWORK_UNREACHABLE',
      'DEVICE_FILE_CONNECTION_TIMEOUT',
      'DEVICE_FILE_AUTH_FAILED',
      'DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED',
      'DEVICE_FILE_SFTP_ENABLE_PENDING',
      'DEVICE_FILE_SFTP_ENABLE_FAILED',
      'DEVICE_FILE_SFTP_RECONNECT_FAILED',
      'DEVICE_FILE_SESSION_DISCONNECTED',
    ]) expect(source).toContain(code)
    expect(source).toContain('reason.details.task_id')
    expect(source).toContain('openTaskWindow(sftpSetupTaskId)')
    expect(source).toContain('const SFTP_SETUP_SUCCESS_MESSAGE = \'已在设备侧启用 SFTP，并完成重新连接。\'')
    expect(source).toContain('ElMessage.success(connection.value.message)')
    expect(source).not.toMatch(/Channel closed|SSHException|ChannelException/)
  })

  it('uses real task paths and direct opaque Desktop actions without a save stage', () => {
    expect(source).toContain("actionLabels: ['取消', '重试', '打开', '所在目录']")
    expect(source).toContain("openTaskResult(row)")
    expect(source).toContain("openTaskResult(row, true)")
    expect(source).toContain("'open_result_dir' : 'open_result'")
    expect(source).toContain("key: 'remote_path'")
    expect(source).toContain("key: 'local_path'")
    expect(source).not.toContain('savedCapabilities')
    expect(source).not.toContain("deliverTask(row, 'save')")
  })

  it('reveals the page after minimal status and loads each region independently', () => {
    expect(source).not.toContain('v-loading="loading"')
    expect(source).toContain('const deviceLoading = ref(false)')
    expect(source).toContain('const queueLoading = ref(false)')
    expect(source).toContain("void loadLocal('', 1)")
    expect(source).toContain('void loadDevices()')
    expect(source).toContain('void recoverTasks()')
    expect(source).toContain('listFileDownloads(siteId.value, 20)')
    expect(source.indexOf('loading.value = false')).toBeLessThan(source.indexOf("void loadLocal('', 1)"))
  })
})
