import { describe, expect, it } from 'vitest'

import source from './DeviceDiagnosticDownloadView.vue?raw'

describe('device diagnostic download view contract', () => {
  it('routes device diagnostics through the file module and a shared export action', () => {
    expect(source).toContain("route-key=\"/device-files/diagnostics\"")
    expect(source).toContain("action: 'devices.diagnostics'")
    expect(source).toContain('startDeviceDiagnosticDownload(selectedUuids.value)')
    expect(source).toContain("ElMessage.warning('请先选择设备')")
    expect(source).toContain("router.push({ name: 'tasks', query: { module: 'devices' } })")
    expect(source).toContain('safeFilePart(pageData.value.site_name || \'当前局点\')')
    expect(source).toContain('localTimestamp()')
  })
})
