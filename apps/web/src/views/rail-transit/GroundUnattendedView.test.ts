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

  it('exposes confirmed deletion for selected historical runs', () => {
    expect(apiSource).toContain('deleteGroundRunHistory')
    expect(apiSource).toContain('method: \'DELETE\'')
    expect(apiSource).toContain('/runs/${encodeURIComponent(runId)}')
    expect(source).toContain('deleteSelectedRunHistory')
    expect(source).toContain('runHistoryDeleteBlocked')
    expect(source).toContain('删除历史记录')
  })

  it('links train details to ping, timeline and existing session analysis', () => {
    expect(source).toContain('getGroundTrain')
    expect(source).toContain('查看长 Ping')
    expect(source).toContain('查看事件时间轴')
    expect(source).toContain('getOnlineMrSession')
    expect(source).toContain('workspace.openOrActivateRoute')
    expect(source).toContain('/rail-transit/online-mr-analysis?session_id=')
  })

  it('keeps the Syslog AP fields together before radio correlation fields', () => {
    const orderedKeys = [
      "key: 'peer_name'",
      "key: 'peer_mac'",
      "key: 'previous_peer_name'",
      "key: 'rssi'",
      "key: 'reason_text'",
      "key: 'interface_name'",
      "key: 'physical_state'",
      "key: 'cfg_event_index'",
      "key: 'cfg_command_source'",
      "key: 'correlation_confidence'",
      "key: 'correlation_delta_ms'",
      "key: 'composite_event_type'",
    ]
    const positions = orderedKeys.map((key) => source.indexOf(key, source.indexOf('const syslogColumns')))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((left, right) => left - right))
    expect(source).toContain('table-id="ground-syslog:v2"')
  })

  it('uses filter-aware deep requests and flexible viewer workspaces', () => {
    const deepWindowStart = source.indexOf('v-model="deepWindowOpen"')
    const deepWindow = source.slice(deepWindowStart, source.indexOf('</NcFloatingWindow>', deepWindowStart))
    expect(source).toContain("requestControllers.has('deep-records')")
    expect(source).toContain('filterIdentity')
    expect(source).toContain('class="deep-records-container"')
    expect(deepWindow).toContain('height="100%"')
    expect(deepWindow).not.toContain('max-height="480"')
    expect(source).toContain('class="ping-chart-workspace"')
    expect(source).toContain('.deep-records-container{flex:1;min-height:0;overflow:hidden}')
  })

  it('uses the runtime decision reason contract in the train list', () => {
    expect(source).toContain("key: 'participates_in_mainline'")
    expect(source).toContain("row.ping_reason_text || '未评估'")
    expect(source).toContain("row.deep_collection_reason_text || '未评估'")
  })

  it('shows the auditable daily queue and current scheduling priority', () => {
    expect(source).toContain("key: 'queue_position'")
    expect(source).toContain('队列位置')
    expect(source).toContain("key: 'scheduling_priority'")
    expect(source).toContain('调度优先级')
  })

  it('uses adaptive shared data tables without fixed viewport-filling frames', () => {
    expect(source).toContain('NcDataTable')
    expect(source).toContain('table-frame')
    expect(source).toContain('useAdaptiveTableHeight')
    expect(source).toContain('auto-height')
    expect(source).toContain('.table-frame{height:auto')
    expect(source).not.toContain('height:clamp(')
    expect(source).toContain('@media(max-width:620px)')
  })

  it('uses one remaining-height workspace for timeline and Syslog consoles', () => {
    expect(source.match(/<NcLogWorkspace/g)).toHaveLength(2)
    expect(source.match(/fill-remaining-height/g)).toHaveLength(2)
    expect(source).toContain('.log-console-pane){display:flex;overflow:hidden}')
    expect(source).toContain('.ground-tabs :deep(.el-tabs__content){flex:1;height:100%;overflow:hidden}')
    expect(source).toContain('.ground-tabs :deep(.el-tab-pane){height:100%;overflow:auto;overscroll-behavior:contain}')
    expect(source).toContain('高级筛选（{{ syslogAdvancedFilterCount }} 个条件）')
    expect(source).toContain('v-model:current-page="timelinePage"')
    expect(source).toContain('v-model:current-page="syslogFilter.page"')
  })

  it('centralizes Chinese labels and exposes packet charts and operation progress', () => {
    expect(source).toContain('groundStatusLabel')
    expect(source).toContain('groundOperationStageLabel')
    expect(source).toContain('GroundPingChart')
    expect(source).toContain('最近 5 分钟')
    expect(source).toContain('最近 1 小时')
    expect(source).toContain('自定义时间')
    expect(source).toContain('实时增量')
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

  it('uses row-scoped Ping context and keeps static historical tabs out of polling', () => {
    expect(source).toContain('train_id: row.train_id')
    expect(source).toContain('mr_id: row.mr_id')
    expect(source).toContain('row.first_sample_at')
    expect(source).toContain('当前时间范围内没有样本，可切换到完整运行时段。')
    expect(source).toContain('getGroundPingSeriesIncremental')
    expect(source).toContain('onDeactivated')
    expect(source).toContain("pollDue('ping-series-incremental', 1_800")
    expect(source).toContain("activeTab.value === 'ping'")
    expect(source).toContain("activeTab.value === 'syslog'")
    expect(source).toContain("pollDue('deep', 4_000")
    expect(source).not.toMatch(/pollDue\('(?:timeline|archives)'/)
    expect(source).toContain('requestFailureCounts')
  })

  it('separates active and terminal operations and exposes archive metadata tabs', () => {
    expect(source).toContain('activeOperation')
    expect(source).toContain('latestTerminalOperation')
    expect(source).toContain('dismissedTerminalOperationIds')
    expect(source).not.toContain('currentOperation')
    for (const label of ['归档概览', '文件清单', 'Ping 汇总', 'Syslog 汇总', '深度会话', '完整性校验', '保留策略']) {
      expect(source).toContain(label)
    }
    for (const field of ['compressed_size_bytes', 'parse_status', 'manifest_sha256']) {
      expect(source).toContain(field)
    }
  })
})
