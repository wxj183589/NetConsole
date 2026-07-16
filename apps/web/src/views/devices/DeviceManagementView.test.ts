import { describe, expect, it } from 'vitest'

import source from './DeviceManagementView.vue?raw'

describe('Device Management Web view', () => {
  it('covers loading, empty, error and success states', () => {
    expect(source).toContain('v-loading="loading"')
    expect(source).toContain('v-if="isEmpty"')
    expect(source).toContain('v-if="error"')
    expect(source).toContain("'empty' : 'success'")
  })

  it('supports filters, detail and safe edit preview', () => {
    expect(source).toContain('connection_status')
    expect(source).toContain('group_id')
    expect(source).toContain('device_type')
    expect(source).toContain('openDetail(row)')
    expect(source).toContain('previewDeviceEdit')
    expect(source).toContain('仅校验和预览，不保存设备或凭据')
    expect(source).not.toContain('type="password"')
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
  })

  it('gates edit preview independently', () => {
    expect(source).toContain("isFeatureEnabled('web.device_edit_preview')")
  })

  it('uses browser file upload and controlled server exports', () => {
    expect(source).toContain('type="file"')
    expect(source).toContain('previewDeviceImport(importFile.value)')
    expect(source).not.toContain('importPath')
    expect(source).not.toContain('output_path')
    expect(source).not.toContain('output_dir')
    expect(source).not.toContain('template_ini')
    expect(source).not.toContain('file_path')
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
    expect(source).toContain('getDeviceTask(taskId)')
    expect(source).toContain('cancelDeviceTask(task.task_id)')
    expect(source).toContain('deviceExportDownloadRequest(task.task_id, task.artifact_id')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain('window.location.assign')
    expect(source).toContain(':disabled="!isTaskActionEnabled(row)"')
  })

  it('builds edit values from the current detail and prioritizes its uuid for native actions', () => {
    expect(source).toContain('function currentDeviceWriteValues()')
    expect(source).toContain('Object.assign(editForm, values)')
    expect(source).toContain('Object.assign(writeForm, values)')
    expect(source).toContain('detail.value?.device.device_uuid || selectedUuids.value[0]')
    expect(source).toContain("action.message || '外部终端已启动'")
    expect(source).not.toContain('等待 Desktop Bridge 执行')
  })
})
