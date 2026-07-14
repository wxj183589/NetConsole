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
  })
})
