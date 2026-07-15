import { describe, expect, it } from 'vitest'

import page from './NetworkToolsView.vue?raw'
import panel from '../../components/network-tools/TcpPortTestPanel.vue?raw'
import toolbox from '../../components/network-tools/NetworkToolboxPanel.vue?raw'
import wireless from '../../components/network-tools/WirelessScanPanel.vue?raw'

describe('unified network tools view', () => {
  it('keeps the existing traffic page and adds TCP port test composition', () => {
    expect(page).toContain("import TrafficTestView")
    expect(page).toContain('<TrafficTestView />')
    expect(page).toContain('<TcpPortTestPanel />')
    expect(page).toContain('<NetworkToolboxPanel />')
    expect(page).toContain('<WirelessScanPanel />')
  })

  it('covers loading, empty, error, running and completed states', () => {
    expect(panel).toContain('v-loading="store.loading"')
    expect(panel).toContain('暂无 TCP 端口测试')
    expect(panel).toContain('v-if="store.error"')
    expect(panel).toContain("'执行中'")
    expect(panel).toContain("latest.status === 'COMPLETED'")
    expect(panel).toContain("isFeatureEnabled('web.network_tools_tcp_port_test')")
  })

  it('keeps calculator, task, cancel, export and Fake Adapter surfaces in module scope', () => {
    expect(toolbox).toContain('calculateIpv4')
    expect(toolbox).toContain('startNetworkTask')
    expect(toolbox).toContain('cancelNetworkTask')
    expect(toolbox).toContain("exportTask('xlsx')")
    expect(wireless).toContain('Fake Adapter')
    expect(wireless).toContain('startWirelessScan')
    expect(wireless).toContain('exportWirelessScan')
  })
})
