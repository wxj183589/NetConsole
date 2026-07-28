import { describe, expect, it } from 'vitest'

import source from './GroundUnattendedView.vue?raw'
import apiSource from '../../api/groundUnattended.ts?raw'

describe('Ground unattended page', () => {
  it('is an independent unattended rail transit workflow', () => {
    for (const label of ['运行概览', '正线车辆', '长 Ping', '深度采集', '时间轴', 'Syslog 日志', '历史归档', '设置']) {
      expect(source).toContain(label)
    }
    expect(source).toContain('地面无人值守')
    expect(source).not.toContain('OnlineMrRealtimeView')
  })

  it('exposes schedule, ping, concurrency, retention and priority controls', () => {
    for (const field of [
      'schedule_start_time', 'schedule_end_time', 'ac_poll_interval_seconds', 'stationary_exclusion_minutes',
      'max_active_trains', 'max_active_mrs', 'fleet_ping_interval_ms', 'fleet_ping_timeout_ms',
      'fleet_ping_warmup_seconds', 'deep_collection_master_enabled',
      'detail_retention_days', 'summary_retention_days', 'togglePriority',
    ]) expect(source).toContain(field)
  })

  it('only clears page polling on unmount and never stops backend work', () => {
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('window.clearTimeout(pollTimer)')
    expect(source).not.toMatch(/onBeforeUnmount\([^)]*stopGroundRun/)
    expect(source).toContain('暂停调度时 AC 轮询与长 Ping 继续')
  })

  it('shows per-controller resident AC polling health', () => {
    expect(source).toContain('AC 常驻轮询')
    expect(source).toContain('health.ac_pollers')
    expect(source).toContain('poller.connection_state')
    expect(source).toContain('poller.reconnect_count')
    expect(source).toContain('每台控制器一个常驻 Task 和一个活动 SSH 会话')
  })

  it('uses the dedicated API including stop-and-archive and confirmed deletion', () => {
    expect(apiSource).toContain('/api/rail-transit/ground-unattended')
    expect(apiSource).toContain('/stop-and-archive')
    expect(apiSource).toContain("explicit_confirmation: true")
  })

  it('links train details to ping, timeline and existing session analysis', () => {
    expect(source).toContain('getGroundTrain')
    expect(source).toContain('查看长 Ping')
    expect(source).toContain('查看事件时间轴')
    expect(source).toContain("name: 'online-mr-analysis'")
  })

  it('shows the auditable daily queue and current scheduling priority', () => {
    expect(source).toContain("key: 'queue_position'")
    expect(source).toContain('队列位置')
    expect(source).toContain("key: 'scheduling_priority'")
    expect(source).toContain('调度优先级')
  })

  it('uses the shared data table with bounded responsive table frames', () => {
    expect(source).toContain('NcDataTable')
    expect(source).toContain('table-frame')
    expect(source).toContain('height:clamp(')
    expect(source).toContain('@media(max-width:620px)')
  })

  it('centralizes Chinese labels and exposes packet charts and operation progress', () => {
    expect(source).toContain('groundStatusLabel')
    expect(source).toContain('groundOperationStageLabel')
    expect(source).toContain('GroundPingChart')
    expect(source).toContain('最近 5 分钟')
    expect(source).toContain('最近 1 小时')
    expect(source).toContain('自定义时间')
    expect(source).toContain('自动刷新')
    expect(apiSource).toContain('/ping-series')
    expect(apiSource).toContain('/syslog-records')
    expect(apiSource).toContain('/operations/latest')
    expect(source).toContain('操作编号')
    expect(source).toContain('设备名称、列车号或 CT/CW')
    expect(source).toContain("label: '设备系统名'")
    expect(source).toContain('groundTransitionContextLabel')
    expect(source).not.toContain('CT Session')
    expect(source).not.toContain('CW Session')
  })
})
