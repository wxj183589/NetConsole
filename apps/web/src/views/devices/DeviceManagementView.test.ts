import { describe, expect, it } from 'vitest'

import source from './DeviceManagementView.vue?raw'

describe('Device Management Web view', () => {
  it('covers loading, empty, error and success states', () => {
    expect(source).toContain('v-loading="loading"')
    expect(source).toContain('v-if="isEmpty"')
    expect(source).toContain('v-if="error"')
    expect(source).toContain("'empty' : 'success'")
  })

  it('supports filters, full detail, write-only credentials and safe edit preview', () => {
    expect(source).toContain('connection_status')
    expect(source).toContain('group_id')
    expect(source).toContain('device_type')
    expect(source).toContain('filters.vendor')
    expect(source).toContain('openDetail(row)')
    expect(source).toContain('detail.interfaces')
    expect(source).toContain('detail.optical_modules')
    expect(source).toContain('detail.lldp_neighbors')
    expect(source).toContain('detail.trackside_ap_business')
    expect(source).toContain('getDeviceHistory')
    expect(source).toContain('previewDeviceEdit')
    expect(source).toContain('仅校验和预览，不保存设备或凭据')
    expect(source).toContain('type="password"')
    expect(source).toContain('autocomplete="new-password"')
    expect(source).toContain('留空会保留原值')
  })

  it('submits background connection tests and restores status by task id', () => {
    expect(source).toContain('startDeviceConnectionTest')
    expect(source).toContain("startTest('SSH')")
    expect(source).toContain("startTest('TELNET')")
    expect(source).toContain("startTest('SNMP')")
    expect(source).toContain("searchParams.set('task_id', taskId)")
    expect(source).toContain("get('task_id')")
    expect(source).toContain('getDeviceConnectionTest')
    expect(source).toContain("isFeatureEnabled('web.device_connection_test')")
    expect(source).toContain('testActive')
    expect(source).toContain('startBatchConnectionTests')
  })

  it('matches current-page selection and row operations', () => {
    expect(source).toContain('function clearSelection()')
    expect(source).toContain('function invertSelection()')
    expect(source).toContain('toggleRowSelection')
    expect(source).toContain('复制设备')
    expect(source).toContain('copyDeviceInfo')
  })

  it('gates edit preview independently', () => {
    expect(source).toContain("isFeatureEnabled('web.device_edit_preview')")
  })

  it('uses safe file upload and controlled server exports', () => {
    expect(source).toContain('type="file"')
    expect(source).toContain('previewDeviceImport(importFile.value)')
    expect(source).not.toContain('importPath')
    expect(source).not.toContain('output_path')
    expect(source).not.toContain('output_dir')
    expect(source).not.toContain('template_ini')
    expect(source).not.toContain('file_path')
    expect(source).toContain('startOmniPeekPreview')
    expect(source).toContain('getOmniPeekPreview')
    expect(source).toContain('selected_item_keys')
    expect(source).toContain('force_export_keys')
    expect(source).toContain('startSecureCrtExportWithTemplate')
    expect(source).toContain('accept=".ini"')
    expect(source).toContain('stopOmniPeekPreview')
    expect(source).toContain('Date.now() + 120_000')
    for (const featureId of [
      'web.device_management_write',
      'web.device_management_collect',
      'web.device_management_import',
      'web.device_management_export',
      'web.device_management_desktop',
    ]) {
      expect(source).toContain(`isFeatureEnabled('${featureId}')`)
    }
  })

  it('persists long-running task ids and supports polling, cancellation and controlled downloads', () => {
    expect(source).toContain('window.sessionStorage.setItem(taskStorageKey')
    expect(source).toContain('failedIds')
    expect(source).toContain('getDeviceTask(taskId)')
    expect(source).toContain('cancelDeviceTask(task.task_id)')
    expect(source).toContain('deviceExportDownloadRequest(task.task_id, task.artifact_id')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain('window.location.assign')
    expect(source).toContain("openTaskWindow({ module: 'devices' })")
    expect(source).not.toContain(':data="trackedTasks"')
  })

  it('builds edit values and launches only configured desktop terminals', () => {
    expect(source).toContain('function currentDeviceWriteValues()')
    expect(source).toContain('Object.assign(editForm, values)')
    expect(source).toContain('Object.assign(writeForm, values)')
    expect(source).toContain('launchExternalTerminals')
    expect(source).toContain('issueExternalTerminalConfirmation')
    expect(source).toContain('getExternalTerminalSettings')
    expect(source).toContain('getPlatformAdapter().selectFile')
    expect(source).toContain('getPlatformAdapter().openExternalUrl')
    expect(source).toContain("terminalSettings[`${terminalType}_path`] = path")
    expect(source).toContain('外部终端配置仅在 Electron Desktop 中可用')
    expect(source).toContain('@closed="clearWriteSecrets"')
    expect(source).not.toContain('等待 Desktop Bridge 执行')
  })
})
