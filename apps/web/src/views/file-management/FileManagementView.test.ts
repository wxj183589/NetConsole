import { describe, expect, it } from 'vitest'

import source from './FileManagementView.vue?raw'

describe('file management read-only view', () => {
  it('supports category filtering, empty/error states and controlled download', () => {
    expect(source).toContain('Session')
    expect(source).toContain('Raw')
    expect(source).toContain('ZIP / 采集包')
    expect(source).toContain('报告 / Artifact')
    expect(source).toContain('暂无符合条件的本地文件')
    expect(source).toContain('el-alert v-if="error"')
    expect(source).toContain('startFileDownload')
    expect(source).toContain('fileDownloadRequest')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain(':href=')
    expect(source).toContain("isFeatureEnabled('web.file_management_download')")
    expect(source).not.toMatch(/>\s*(上传|删除|重命名)\s*</)
  })

  it('recovers task status by opaque task id and stops polling on unmount', () => {
    expect(source).toContain('localStorage')
    expect(source).toContain('recoverTasks')
    expect(source).toContain('getFileDownloadTask')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('clearTimeout')
    expect(source).toContain('disconnectDeviceFiles(connectionId')
    expect(source).not.toContain('absolute_path')
  })

  it('keeps remote browsing behind its own gate and excludes unsupported desktop actions', () => {
    expect(source).toContain('connectDeviceFiles')
    expect(source).toContain('listRemoteDevices')
    expect(source).not.toContain("from '../../api/deviceManagement'")
    expect(source).toContain('listRemoteFiles')
    expect(source).toContain('startRemoteFileDownload')
    expect(source).toContain('Mesh 日志')
    expect(source).toContain("isFeatureEnabled('web.file_management_remote')")
    expect(source).not.toContain('requestWinScp')
    expect(source).not.toContain('requestOpenResultDirectory')
    expect(source).not.toMatch(/>\s*(上传|删除|重命名)\s*</)
  })
})
