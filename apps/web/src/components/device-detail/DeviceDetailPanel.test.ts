import { describe, expect, it } from 'vitest'

import source from './DeviceDetailPanel.vue?raw'
import deviceManagementTypes from '../../types/deviceManagement.ts?raw'

describe('DeviceDetailPanel', () => {
  it('uses backend section capabilities and shares one lazy detail presentation', () => {
    expect(source).toContain('visible_sections')
    expect(source).not.toContain('capabilities?.sections')
    expect(source).not.toContain('device.interfaces.read')
    expect(source).not.toContain('normalizeOverview')
    expect(source).toContain('platform_facts')
    expect(source).toContain('command_profile')
    expect(source).toContain('task_facts')
    expect(source).toContain('counts')
    expect(source).toContain('getSectionFilterOptions')
    expect(source).toContain('sectionQuery.status')
    expect(source).toContain('sectionQuery.severity')
    expect(source).toContain('mapBusinessAssociation')
    expect(source).toContain('item.fit_ap?.mac_address')
    expect(source).not.toContain("key: 'ac_type'")
    expect(source).not.toContain("key: 'mr_type'")
    expect(source).not.toContain("key: 'switch_type'")
    expect(source).not.toContain('management_address')
    expect(source).toContain('duration_seconds')
    expect(source).toContain('neighbor_ip')
    expect(source).toContain('lldp_truncated')
    expect(source).not.toContain('input_rate')
    expect(source).not.toContain('output_rate')
    expect(source).not.toContain('input_errors')
    expect(source).not.toContain('output_errors')
    expect(source).not.toContain('crc_errors')
    expect(source).not.toContain('error_count')
    expect(source).not.toContain('last_change')
    expect(source).toContain('getDeviceDetailSection')
    expect(source).toContain('sectionCache')
    expect(source).toContain('sectionQuery.search')
    expect(source).toContain("['interfaces', 'optical', 'lldp'].includes(section)")
    expect(source).toContain('response.truncated')
    expect(source).toContain('sourceReason')
    expect(source).toContain('page_size')
    expect(source).toContain('完整详情')
    expect(source).toContain('刷新全部')
    expect(source).not.toMatch(/if \([^)]*(vendor|version|threshold)/i)
    expect(source).toContain("normal: '正常'")
    expect(source).toContain("notice: '注意'")
    expect(source).toContain("critical: '严重告警'")
    expect(source).toContain("matched: '已关联'")
    expect(source).toContain("unresolved: '未关联'")
    expect(source).toContain("pending: '等待中'")
    expect(source).toContain("running: '运行中'")
    expect(source).toContain("succeeded: '已成功'")
    expect(source).toContain("cancelled: '已取消'")
    expect(source).toContain("aborted: '已中止'")
    expect(source).not.toContain('threshold_source')
    expect(source).toContain("'optical module is not present': '未检测到光模块'")
    expect(source).toContain("'rx power is missing or <= -35 dbm': '接收功率缺失或不高于 -35 dBm'")
    expect(source).toContain("'port is down': '端口已断开'")
    expect(source).toContain("'rx threshold is missing': '接收功率阈值缺失'")
    expect(source).toContain("'rx power below alarm low threshold': '接收功率低于告警低阈值'")
    expect(source).toContain('exactDisplayValueLabels[key]?.[normalizedValue]')
    expect(source).toContain('formatEnumeratedValue(column.key, row[column.key], row)')
    expect(source).toContain('formatEnumeratedValue(column[1], row[column[1]], row)')
    expect(source).toContain('formatDetailValue(field.key, field.value, field.context)')
    expect(source).toContain('displayInterfaceName')
    expect(source).toContain("key === 'severity_reason' && isNormalSeverity(context?.severity)")
    expect(source).toContain("normalizedValue === 'normal' || normalizedValue === '正常'")
    expect(source).toContain("['alarm', 'critical', 'no_light', 'no_module', 'link_abnormal', 'link_down', 'offline'].includes(severity)")
    expect(source).toContain("['warning', 'notice', 'not_collected', 'skipped'].includes(severity)")
    expect(source).toContain("no_module: '无光模块'")
    expect(source).toContain('color: var(--nc-danger)')
    expect(source).toContain('color: var(--nc-warning)')
    expect(source).not.toContain("['连接器', 'connector_type'], ['状态', 'status']")
    const businessColumns = source
      .split("business: [")[1]
      .split('const visibleSections')[0]
    for (const removedColumnKey of ['ac_id', 'ac_name', 'ac_ip', 'ap_model', 'ap_state', 'switch_name', 'switch_interface', 'optical_severity', 'mr_name', 'mr_phase', 'mr_duration_seconds', 'mr_task_id']) {
      expect(businessColumns).not.toContain(`key: '${removedColumnKey}'`)
    }
    expect(source).toContain(':height="sectionTableHeight"')
    expect(source).toContain("props.mode === 'page' ? 'max(320px, calc(100dvh - 390px))'")
    expect(source).not.toContain('820px')
    expect(source).toContain("props.mode === 'drawer' ? 560")
  })

  it('centralizes missing value formatting and task client lifecycle', () => {
    expect(source).toContain("if (value === null || value === undefined || value === '') return '—'")
    expect(source).toContain('taskStore.acquirePolling(pollingConsumer)')
    expect(source).toContain('taskStore.releasePolling(pollingConsumer)')
    expect(source).toContain('refreshDeviceDetails')
    expect(source).toContain('openTaskWindow')
    expect(source).toContain('reloadAfterRefresh')
    expect(source).toContain('sectionLoadGeneration')
    expect(source).toContain('response.source.task_id')
    expect(source).toContain('interfaceDetailGeneration')
    expect(source).toContain('interfaceDetailAbortController')
    expect(source).toContain('new AbortController()')
    expect(source).toContain('controller.signal')
    expect(source).toContain('overview.command_profile?.executable')
    expect(source).toContain('任务状态刷新失败')
    expect(source).toContain('任务窗口打开失败')
    expect(source).not.toContain('JSON.stringify(selectedRecord')
    expect(source).not.toContain('JSON.stringify')
    expect(source).not.toMatch(/background:\s*#[0-9a-f]{3,8}/i)
  })

  it('不再向前端暴露光模块状态字段', () => {
    const transceiverContract = deviceManagementTypes
      .split('export interface DeviceTransceiverRecord')[1]
      .split('export interface DeviceLldpRecord')[0]
    expect(transceiverContract).not.toContain('status')
    expect(transceiverContract).not.toContain('threshold_source')
    expect(source).not.toContain("{ label: '状态', key: 'status', width: 100 }")
  })

  it('收窄关联业务的前端公开类型', () => {
    const acFacts = deviceManagementTypes
      .split('export interface DeviceAcApAssociationFacts')[1]
      .split('export interface DeviceMrSessionAssociationFacts')[0]
    for (const removedField of ['ac_id', 'ac_name', 'ip_address', 'model', 'state_display', 'switch_name', 'switch_interface', 'optical_severity']) {
      expect(acFacts).not.toMatch(new RegExp(`\\b${removedField}\\??:`))
    }

    const mrFacts = deviceManagementTypes
      .split('export interface DeviceMrSessionAssociationFacts')[1]
      .split('export type DeviceBusinessAssociationType')[0]
    for (const removedField of ['mr_name', 'phase', 'duration_seconds', 'task_id']) {
      expect(mrFacts).not.toMatch(new RegExp(`\\b${removedField}\\??:`))
    }
  })
})
