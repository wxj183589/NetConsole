import { expect, test, type Page } from '@playwright/test'

const root = '/api/rail-transit/ground-unattended'
const now = '2026-11-07T09:00:00+08:00'
const paged = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 50, total_exact: true })
const profile = {
  site_id: 'synthetic-ground', enabled: true, schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai',
  ac_poll_interval_seconds: 10, stationary_exclusion_minutes: 10, ac_stale_grace_seconds: 120,
  ac_ping_correlation_tolerance_seconds: 15, ap_switch_before_seconds: 5, ap_switch_after_seconds: 5,
  max_active_trains: 2, max_active_mrs: 4, max_starting_mrs: 2, max_finalizing_mrs: 2,
  deep_collection_master_enabled: true, deep_fping_required: true,
  deep_fping: { enabled: true, target: '', preset_key: '', preset_name: '', packet_size: 64, interval_ms: 100, timeout_ms: 1000, loss_warn_percent: 1, latency_warn_ms: 100 },
  fleet_ping_interval_ms: 1000, fleet_ping_timeout_ms: 4000, fleet_ping_packet_size: 64, fleet_ping_shard_size: 64, fleet_ping_warmup_seconds: 0,
  udp_listen_host: '127.0.0.1', udp_listen_port: 5514, udp_queue_capacity: 20000, raw_flush_interval_seconds: 1, raw_flush_record_count: 100,
  event_batch_size: 100, event_batch_interval_seconds: 1, boot_time_tolerance_seconds: 120, config_check_cooldown_seconds: 1800,
  syslog_server_ip: '127.0.0.1', syslog_server_port: 5514, allow_external_syslog_address: false,
  ping_raw_retention_days: 30, syslog_raw_retention_days: 30, minimum_valid_collection_minutes: 10,
  preferred_collection_minutes: 20, maximum_collection_minutes: 30, start_jitter_seconds: 3, start_batch_size: 1,
  detail_retention_days: 30, summary_retention_days: 180, storage_warning_free_gb: 5, storage_critical_free_gb: 1,
}
const syslog = (id: number, role: 'CT' | 'CW', event: string) => ({
  receive_time: now, device_time: now, source_ip: role === 'CT' ? '192.0.2.10' : '192.0.2.11', source_port: 514,
  hostname: `synthetic-${role}`, system_name: `SYNTHETIC-${role}`, facility: 'WMESH', severity: id === 2 ? 'warning' : 'info',
  train_id: 'train-001', train_no: '001', device_uuid: `mr-${role}`, mr_name: `合成 MR ${role}`, mr_role: role,
  identity_status: 'VERIFIED', parse_status: 'PARSED', data_quality: 'VALID', clock_offset_ms: 100,
  raw_text: `<134> synthetic WMESH ${event} AP-01 RSSI -55 #${id}`, raw_file_id: 'synthetic-raw-1', raw_file_status: 'OPEN',
  raw_line_number: id, global_receive_sequence: id, source_receive_sequence: id, archive_entry: '', data_source: 'ACTIVE', display_enriched: false,
  event_type: event, event_family: 'WMESH', interface_name: 'WLAN-MESH0', interface_type: 'WLAN', physical_state: 'UP',
  cfg_event_index: '', cfg_command_source: '', cfg_source: '', cfg_destination: '', expected_internal_change: false,
  correlation_status: 'CORRELATED', correlation_confidence: 'HIGH', correlation_delta_ms: 120,
  correlated_event_ids: [100 + id], composite_event_type: 'AP_SWITCH',
  peer_ap_id: 'ap-01', peer_name: '区间 AP 01', peer_mac: '00:aa:bb:cc:dd:01', peer_radio_mac: '00:aa:bb:cc:ee:01',
  previous_peer_ap_id: 'ap-00', previous_peer_name: '区间 AP 00', previous_peer_mac: '00:aa:bb:cc:dd:00', previous_peer_radio_mac: '',
  station: '合成站', section: '合成区间', previous_station: '前一站', previous_section: '', rssi: -55,
  previous_rssi: -66, reason_code: '', reason_text: '合成切换', resolution_status: 'RESOLVED', parsed_details: { display_name_source: 'AP_IDENTITY', observation: `synthetic-${id}` },
})
const records = [syslog(1, 'CT', 'MESH_ACTIVELINK_SWITCH'), syslog(2, 'CW', 'MESH_LINKDOWN')]
const item = (name: string, label: string, status: string, size: number) => ({
  name, label, status, size_bytes: size, started_at: now, ended_at: '', updated_at: now,
  error: status === 'FAILED' ? '合成采集源无数据' : '', raw_file: `sessions/synthetic/${name}.log`, exists: status !== 'FAILED',
})
const collector = (role: 'CT' | 'CW', state: string) => ({
  run_id: 'synthetic-run', train_id: 'train-001', train_no: '001', mr_id: `mr-${role}`, mr_role: role,
  management_ip: role === 'CT' ? '192.0.2.10' : '192.0.2.11', operation_id: `deep-${role}`, collector_session_id: `session-${role}`,
  state, source_state: state, state_reason: '按策略持续采集', started_at: now, ended_at: '', last_record_at: now,
  record_count: 50, bytes_written: role === 'CT' ? 4096 : 2048, current_ap: '区间 AP 01', station: '合成站', section: '合成区间',
  last_error: '', retry_count: 0, fping_status: 'RUNNING', fping_target_ip: '192.0.2.1', fping_started_at: now,
  fping_last_data_at: now, fping_sample_count: 50, fping_interval_ms: 100, fping_timeout_ms: 1000, fping_packet_size: 64,
  fping_loss_percent: 0, fping_avg_latency_ms: 2, fping_latest_latency_ms: 2, fping_error: '', data_integrity_status: 'COMPLETE',
  progress_kind: 'CONTINUOUS', items: [
    item('fping', '持续 Ping', state, 1024), item('wmesh', 'WMESH 事件', state, 2048),
    item('rssi', 'RSSI 观测', state, 1024), item('radio', '射频配置', 'FAILED', 0),
  ],
})
const tasks = [collector('CT', 'RUNNING'), collector('CW', 'COMPLETED')]

async function mockApi(page: Page) {
  const unexpected: string[] = []
  const syslogQueries: URL[] = []
  const deepQueries: URL[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let body: unknown
    if (path === '/api/features') body = { items: ['overview', 'heartbeat', 'ac_mesh_link', 'quick_ping', 'syslog', 'deep', 'timeline', 'health', 'archives', 'settings'].map(key => ({ feature_id: `ground_unattended.${key}`, visible: true, enabled: true })) }
    else if (path === `${root}/status`) body = { site_id: profile.site_id, enabled: true, service_state: 'RUNNING', paused: false, running_mode: 'DEEP', active_run_id: 'synthetic-run', active_run_state: 'RUNNING', active_run_date: '2026-11-07', latest_run_id: 'synthetic-run', latest_run_date: '2026-11-07', latest_run_state: 'RUNNING', schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai', ping_target_count: 2, mainline_train_count: 1, active_deep_train_count: 1 }
    else if (path === `${root}/profile`) body = profile
    else if (path === `${root}/runs`) body = paged([{ run_id: 'synthetic-run', run_date: '2026-11-07', state: 'RUNNING', data_availability: 'ACTIVE_RAW', actual_started_at: now }])
    else if (path === `${root}/syslog-records`) {
      syslogQueries.push(url)
      body = { ...paged(records), diagnostics: { source_kind: 'ACTIVE', data_availability: 'ACTIVE_RAW', files_scanned: 1, records_scanned: 2, truncated: false },
        statistics: { today_received: 2, active_files: 1, parse_failed_files: 0, raw_missing_files: 0, wmesh_events: 2, data_status: 'ACTIVE_RAW' } }
    }
    else if (path === `${root}/deep-collections/tasks`) { deepQueries.push(url); body = { ...paged(tasks), statistics: { task_count: 2, running: 1, completed: 1, failed: 0, partial: 0 } } }
    else if (path === `${root}/deep-collections/records`) {
      deepQueries.push(url)
      body = { collector: tasks.find(task => task.operation_id === url.searchParams.get('operation_id')) || tasks[0],
        records: [{ sequence: 1, timestamp: now, category: 'WMESH', source: 'collector', text: '合成 WMESH 链路采集开始' },
          { sequence: 2, timestamp: now, category: 'RSSI', source: 'collector', text: '合成 RSSI -55 dBm' }], next_cursor: '2', has_more: false }
    }
    else if (path === `${root}/health`) body = { site_id: profile.site_id, status: 'HEALTHY', supervisor_running: true, run_state: 'RUNNING', syslog_receiver_alive: true, syslog_writer_alive: true, syslog_parser_alive: true }
    else if (path === `${root}/heartbeat`) body = { run_id: 'synthetic-run', run_state: 'RUNNING', mr_counts: { ONLINE: 2 }, train_counts: { BOTH_ONLINE: 1 }, mrs: [], trains: [] }
    else if (path === `${root}/trains` || path === `${root}/ping-targets` || path === `${root}/quick-ping` || path === `${root}/deep-collections` || path === `${root}/archives` || path === `${root}/timeline`) body = paged([])
    else if (path === `${root}/syslog-transport-status`) body = { receiver_running: true, receiver_state: 'RUNNING', port_state: 'LISTENING', ports_match: true }
    else if (path === `${root}/history`) body = { ...paged([]), sources: {} }
    else if (path.endsWith('/ipv4-addresses')) body = paged([])
    else if (path.endsWith('/online-mr-control/presets')) body = { ping: [], traffic: [] }
    else if (path.includes('/operations/')) body = null
    else { unexpected.push(`${route.request().method()} ${path}`); await route.fulfill({ status: 404, json: { detail: 'Unmocked API' } }); return }
    await route.fulfill({ json: body })
  })
  return { unexpected, syslogQueries, deepQueries }
}

test('Syslog filters, column settings, detail and raw record', async ({ page }, testInfo) => {
  const api = await mockApi(page), errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/tests/visual/ground.html?netconsole_host=electron')
  await page.getByRole('tab', { name: 'Syslog 日志', exact: true }).click()
  const section = page.locator('.ground-subpage').filter({ has: page.locator('.syslog-statistics') })
  await expect(section.locator('.syslog-statistics')).toContainText('今日接收日志')
  await expect(section.locator('.el-table__body tr')).toHaveCount(2)
  await page.screenshot({ path: testInfo.outputPath('syslog-01-main-list.png'), fullPage: true })

  await section.getByPlaceholder('列车 ID').fill('train-001')
  await section.getByRole('button', { name: /高级筛选/ }).click()
  await section.getByPlaceholder('原始内容关键字').fill('WMESH')
  await section.getByRole('button', { name: '查询', exact: true }).click()
  await expect.poll(() => api.syslogQueries.at(-1)?.searchParams.get('keyword')).toBe('WMESH')
  expect(api.syslogQueries.at(-1)?.searchParams.get('train_id')).toBe('train-001')
  await page.screenshot({ path: testInfo.outputPath('syslog-02-advanced-filters.png'), fullPage: true })

  await section.getByRole('button', { name: '列设置' }).click()
  await expect(page.locator('.nc-column-settings:visible')).toContainText('原始内容')
  await page.screenshot({ path: testInfo.outputPath('syslog-03-column-settings.png'), fullPage: true })
  await section.getByRole('button', { name: '列设置' }).click()
  await expect(page.locator('.nc-column-settings:visible')).toHaveCount(0)
  await section.getByRole('button', { name: '详情', exact: true }).first().click()
  const drawer = page.getByRole('dialog', { name: 'Syslog 原始记录详情' })
  await expect(drawer).toContainText('合成 MR CT')
  await expect(drawer.locator('pre.raw-record').last()).toContainText('<134> synthetic WMESH')
  await page.screenshot({ path: testInfo.outputPath('syslog-04-detail-raw.png'), fullPage: true })
  await drawer.locator('pre.raw-record').last().scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('syslog-05-raw-message.png'), fullPage: true })
  expect(errors).toEqual([])
  expect(api.unexpected).toEqual([])
})

test('Deep tasks, child projects, logs and files', async ({ page }, testInfo) => {
  const api = await mockApi(page), errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/tests/visual/ground.html?netconsole_host=electron')
  await page.getByRole('tab', { name: '深度采集', exact: true }).click()
  const section = page.locator('.deep-page')
  await expect(section.locator('.deep-stats')).toContainText('采集任务')
  await expect(section.locator('.el-table__body tr')).toHaveCount(2)
  await page.screenshot({ path: testInfo.outputPath('deep-01-tasks.png'), fullPage: true })

  await section.getByRole('button', { name: '详情', exact: true }).first().click()
  const drawer = page.getByRole('dialog', { name: '001 / CT' })
  await expect(drawer.locator('.child-progress')).toHaveCount(4)
  await page.screenshot({ path: testInfo.outputPath('deep-02-progress-projects.png'), fullPage: true })
  await drawer.getByRole('tab', { name: '采集项目' }).click()
  await expect(drawer.locator('.el-table:visible .el-table__body tr')).toHaveCount(4)
  await page.screenshot({ path: testInfo.outputPath('deep-03-child-items.png'), fullPage: true })
  await drawer.getByRole('tab', { name: '实时日志' }).click()
  await expect(drawer.locator('.deep-logs')).toContainText('合成 WMESH 链路采集开始')
  expect(api.deepQueries.some(url => url.pathname.endsWith('/records') && url.searchParams.get('operation_id') === 'deep-CT')).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('deep-04-live-logs.png'), fullPage: true })
  await drawer.getByRole('tab', { name: '采集文件' }).click()
  await expect(drawer).toContainText('sessions/synthetic/wmesh.log')
  await page.screenshot({ path: testInfo.outputPath('deep-05-files.png'), fullPage: true })
  expect(errors).toEqual([])
  expect(api.unexpected).toEqual([])
})
