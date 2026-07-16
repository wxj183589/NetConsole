import { describe, expect, it } from 'vitest'

import page from './NetworkToolsView.vue?raw'
import toolbox from '../../components/network-tools/NetworkToolboxPanel.vue?raw'
import wireless from '../../components/network-tools/WirelessScanPanel.vue?raw'
import traffic from './TrafficTestView.vue?raw'

describe('unified network tools view', () => {
  it('keeps toolbox, traffic and wireless as single owned surfaces', () => {
    expect(page).toContain('<NetworkToolboxPanel />')
    expect(page).not.toContain('TrafficTestView')
    expect(page).not.toContain('WirelessScanPanel')
    expect(traffic).toContain('<TcpPortTestPanel />')
  })

  it('keeps calculator, task, cancel, export and WLAN surfaces in module scope', () => {
    expect(toolbox).toContain('calculateIpv4')
    expect(toolbox).toContain('startNetworkTask')
    expect(toolbox).toContain('cancelNetworkTask')
    expect(toolbox).toContain("exportTask('xlsx')")
    expect(wireless).toContain('startWirelessScan')
    expect(wireless).toContain('exportWirelessScan')
    expect(wireless).toContain('deleteWirelessProject')
    expect(wireless).toContain('ElMessageBox.confirm')
    expect(wireless).toContain('project_name')
    expect(wireless).toContain('changeRunPage')
    expect(wireless).toContain('getWirelessRunDetail')
    expect(wireless).toContain('scan_source')
  })

  it('recovers module tasks from the shared task store without local storage ids', () => {
    expect(toolbox).toContain('useTaskStore')
    expect(toolbox).toContain('listNetworkTaskResults')
    expect(toolbox).toContain('getNetworkExportArtifact')
    expect(toolbox).toContain('cancelNetworkTask')
    expect(toolbox).not.toContain('localStorage')
    expect(wireless).toContain('useTaskStore')
    expect(wireless).toContain('getWirelessTask')
    expect(wireless).toContain('cancelWirelessTask')
    expect(wireless).toContain('getWirelessExportArtifact')
    expect(wireless).not.toContain('localStorage')
  })
})
