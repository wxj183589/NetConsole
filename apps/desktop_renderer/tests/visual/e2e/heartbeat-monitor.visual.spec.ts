import { expect, test, type Page } from '@playwright/test'

// Only synthetic API responses: the real Vue components and fetch client run in Chrome.
const root = '/api/rail-transit/ground-unattended'
const now = '2026-11-07T09:00:00+08:00'
const run = { run_id: 'mock-run-v2', run_date: '2026-11-07', state: 'RUNNING', data_availability: 'ACTIVE_RAW', actual_started_at: now }
const endpoints = ['CT', 'CW'].map((role, i) => ({
  endpoint: role, mr_id: `mock-mr-${role}`, mr_name: `合成 MR ${role}`, management_ip: `192.0.2.${10 + i}`,
  backup_management_ip: role === 'CT' ? '192.0.2.20' : '', enabled: true, radio_overall_state: 'UP',
  radio_interfaces: [], cfg_command_source: '', online_status: 'ONLINE',
}))
const train = {
  train_id: 'mock-train', train_no: '001', train_name: '合成列车 001', endpoints,
  enabled: true, priority: false, eligibility_status: 'ELIGIBLE', coverage_status: 'PENDING',
  current_ap_name: '', station: '', section: '', location_match_status: 'UNKNOWN', current_collection: null,
  deep_collection_enabled: false, monitor_only: true, missing_endpoints: [], warnings: [],
}
const profile = {
  site_id: 'mock-ground', enabled: true, schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai',
  ac_poll_interval_seconds: 10, stationary_exclusion_minutes: 10, ac_stale_grace_seconds: 120,
  ac_ping_correlation_tolerance_seconds: 15, ap_switch_before_seconds: 5, ap_switch_after_seconds: 5,
  max_active_trains: 2, max_active_mrs: 4, max_starting_mrs: 2, max_finalizing_mrs: 2,
  deep_collection_master_enabled: false, deep_fping_required: true,
  deep_fping: { enabled: true, target: '', preset_key: '', preset_name: '', packet_size: 64, interval_ms: 100, timeout_ms: 1000, loss_warn_percent: 1, latency_warn_ms: 100 },
  fleet_ping_interval_ms: 1000, fleet_ping_timeout_ms: 4000, fleet_ping_packet_size: 64, fleet_ping_shard_size: 64, fleet_ping_warmup_seconds: 0,
  udp_listen_host: '127.0.0.1', udp_listen_port: 5514, udp_queue_capacity: 20000, raw_flush_interval_seconds: 1, raw_flush_record_count: 100,
  event_batch_size: 100, event_batch_interval_seconds: 1, boot_time_tolerance_seconds: 120, config_check_cooldown_seconds: 1800,
  syslog_server_ip: '127.0.0.1', syslog_server_port: 5514, allow_external_syslog_address: false,
  ping_raw_retention_days: 30, syslog_raw_retention_days: 30, minimum_valid_collection_minutes: 10,
  preferred_collection_minutes: 20, maximum_collection_minutes: 30, start_jitter_seconds: 3, start_batch_size: 1,
  detail_retention_days: 30, summary_retention_days: 180, storage_warning_free_gb: 5, storage_critical_free_gb: 1,
}
const heartbeat = {
  run_id: run.run_id, run_state: 'RUNNING', mr_counts: { ONLINE: 2, OFFLINE: 0 }, train_counts: { BOTH_ONLINE: 1 },
  mrs: endpoints.map((endpoint) => ({
    mr_uuid: endpoint.mr_id, train_id: train.train_id, train_no: train.train_no, mr_name: endpoint.mr_name,
    role: endpoint.endpoint, status: 'ONLINE', engine_state: 'RUNNING', last_success_at: now,
    unreachable_since: '', last_recovery_at: '', consecutive_recovery_successes: 0, updated_at: now,
    ip_states: [endpoint.management_ip, endpoint.backup_management_ip].filter(Boolean).map(ip => ({
      ip, sent_count: 60, received_count: 59, lost_count: 1, min_rtt_ms: 1, avg_rtt_ms: 2, max_rtt_ms: 3,
    })),
  })), trains: [{ train_id: train.train_id, train_no: train.train_no, status: 'BOTH_ONLINE' }],
}
const health = {
  site_id: profile.site_id, status: 'HEALTHY', supervisor_running: true, run_state: 'RUNNING', run_elapsed_seconds: 3600,
  ping_target_count: 3, ping_process_count: 1, ping_sample_rate_per_second: 3, ping_last_sample_at: now,
  ping_sample_write_duration_ms: 0.5, ping_worker_warnings: [], udp_running: true,
  syslog_receiver_alive: true, syslog_writer_alive: true, syslog_parser_alive: true,
  udp_received_count: 20000, udp_dropped_count: 0, raw_write_failed_count: 0,
  disk_total_bytes: 100000000000, disk_free_bytes: 80000000000, raw_file_count: 12,
  raw_write_rate_bytes_per_second: 2048, archive_pending_count: 0, archive_failed_count: 0, ac_pollers: [],
}
const stats = { sent: 10, received: 9, lost: 1, loss_rate_percent: 10, min_rtt_ms: 1, avg_rtt_ms: 2, max_rtt_ms: 3, jitter_ms: 1, current_consecutive_loss: 0, max_consecutive_loss: 1 }
const diagnostics = { source_kind: 'ACTIVE', data_availability: 'ACTIVE_RAW', files_scanned: 1, records_scanned: 100, truncated: false }


const rootMrs = heartbeat.mrs.map((mr, index) => ({ ...mr, resolved_ap_name: `车载 AP ${index ? 'CW' : 'CT'}`, station: '', section: '车辆段', identity_status: 'matched', ac_data_status: 'fresh', current_rtt_ms: index ? null : 2.8, status: index ? 'OFFLINE' : 'ONLINE' }))
const currentHeartbeat = {
  ...heartbeat, total: 10, total_mrs: 20, page: 1, page_size: 50, stations: [], train_counts: { CT_ONLY: 10 },
  trains: Array.from({ length: 10 }, (_, index) => ({ train_id: `train-${index}`, train_no: String(index + 1).padStart(3, '0'), status: 'CT_ONLY' })),
  mrs: Array.from({ length: 10 }, (_, index) => rootMrs.map(mr => ({ ...mr, mr_uuid: `${mr.mr_uuid}-${index}`, train_id: `train-${index}`, train_no: String(index + 1).padStart(3, '0') }))).flat(),
}
async function mockHeartbeat(page: Page) {
  const unexpected: string[] = []
  const applied: unknown[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url()), path = url.pathname
    const paged = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 100, total_exact: true })
    let body: unknown
    if (path === '/api/features') body = { items: [...['overview', 'heartbeat', 'ac_mesh_link', 'quick_ping', 'syslog', 'deep', 'timeline', 'health', 'archives', 'settings'].map(key => `ground_unattended.${key}`), 'capability.ground_unattended.quick_ping', 'capability.ground_unattended.heartbeat_inventory_manage'].map(feature_id => ({ feature_id, enabled: true, visible: true })) }
    else if (path === `${root}/heartbeat/inventory/preview`) body = { site_id: 'mock-ground', action: route.request().postDataJSON().action, revision: 'mock-revision', added_count: 1, updated_count: 2, disabled_count: 0, conflict_count: 0, retained_history_count: 9, train_count: 10, device_count: 20, affected_history_count: 9, conflicts: [] }
    else if (path === `${root}/heartbeat/inventory/apply`) { applied.push(route.request().postDataJSON()); body = {} }
    else if (path === `${root}/status`) body = { ...run, site_id: profile.site_id, enabled: true, service_state: 'RUNNING', active_run_id: run.run_id, active_run_state: 'RUNNING', active_run_date: run.run_date, latest_run_id: run.run_id, latest_run_date: run.run_date, latest_run_state: 'RUNNING', schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: profile.timezone, ping_target_count: 3, mainline_train_count: 1, active_deep_train_count: 0 }
    else if (path === `${root}/profile`) body = profile
    else if (path === `${root}/syslog-transport-status`) body = { state: 'RUNNING', message: '' }
    else if (path === `${root}/runs`) body = paged([run])
    else if (path === `${root}/trains`) body = paged([train])
    else if (path === `${root}/health`) body = health
    else if (path === `${root}/heartbeat`) body = currentHeartbeat
    else if (path.includes('/operations/')) body = null
    else if (path.endsWith('/monitoring')) {
      const end = Date.parse(url.searchParams.get('end_time')!), start = Date.parse(url.searchParams.get('start_time')!), time = new Date(end - 30000).toISOString()
      const mr = currentHeartbeat.mrs.find(row => path.includes(row.mr_uuid)) || currentHeartbeat.mrs[0]!
      body = { mr, queried_start: new Date(start).toISOString(), queried_end: new Date(end).toISOString(), events_truncated: false, run_sent_count: 3600, run_lost_count: 9,
        series: { run_id: run.run_id, statistics: stats, diagnostics, window_statistics: Object.fromEntries([1,10,30,60].map(minutes => [String(minutes), { sent_count: minutes*60, lost_count: minutes, loss_rate_percent: 1.67 }])), points: Array.from({ length: 300 }, (_, index) => ({ ts: new Date(end - (300-index)*1000).toISOString(), target_ip: '192.0.2.10', ok: index%40 !== 0, rtt_ms: index%40 ? 2+Math.sin(index/10) : null })) },
        mesh_events: [{ id: 1, event_time: time, device_time: time, receive_time: time, event_type: 'MESH_ACTIVELINK_SWITCH', source: 'SYSLOG', old_ap_name: '区间 AP A', new_ap_name: '区间 AP B', old_bssid: '00:11:22:33:44:55', bssid: '00:11:22:33:44:66', rssi: -52, raw_text: 'Synthetic WMESH activelink switch A -> B', raw_file_id: 'mock-raw', raw_line_number: 1, event_time_source: 'DEVICE_TIME', data_quality: 'COMPLETE', identity_status: 'matched' }],
        peer_intervals: [{ start: new Date(end-280000).toISOString(), end: new Date(end-30000).toISOString(), peer_name: '区间 AP A', bssid: '00:11:22:33:44:55', rssi: -50, source: 'SYSLOG', device_time: time, receive_time: time }],
      }
    }
    else if (path === `${root}/ping-targets` || path === `${root}/timeline` || path === `${root}/syslog-records` || path === `${root}/deep-collections` || path === `${root}/archives` || path === `${root}/history` || path.endsWith('/ipv4-addresses')) body = paged([])
    else if (path === `${root}/quick-ping`) body = { ...paged([]), active_ips: {} }
    else if (path.endsWith('/online-mr-control/presets')) body = { ping: [], traffic: [] }
    else if (path.endsWith('/train-online/controllers')) body = []
    else if (path === '/api/ac-management/mesh-links/summary') body = { registered_mrs: 2, online_mrs: 2, data_status: 'fresh', age_seconds: 1 }
    else if (path === '/api/ac-management/mesh-links/raw-tail') body = { available: false, lines: [] }
    else if (path.startsWith('/api/ac-management/mesh-links/')) body = paged([])
    else { unexpected.push(path); await route.fulfill({ status: 404, json: { detail: 'Unmocked API' } }); return }
    await route.fulfill({ json: body })
  })
  return { unexpected, applied }
}

test('Heartbeat compact rows and unified MR evidence drawer', async ({ page }, testInfo) => {
  const { unexpected, applied } = await mockHeartbeat(page), errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/tests/visual/ground.html?netconsole_host=electron')
  await page.getByRole('tab', { name: '心跳检测', exact: true }).click()
  await expect(page.locator('.heartbeat-page .train-row')).toHaveCount(10)
  await expect(page.locator('.heartbeat-page')).toContainText('仅 CT 可达')
  await expect(page.locator('.heartbeat-page .mr-card').first()).toContainText('合成 MR CT')
  await expect(page.locator('.heartbeat-page .mr-card').first().locator('.el-tag')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('heartbeat-01-compact-trains.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '同步监测设备' }).click()
  let management = page.getByRole('dialog', { name: '同步设备预览' })
  await expect(management).toContainText('1 / 2 / 0 / 0')
  await page.screenshot({ path: testInfo.outputPath('heartbeat-05-sync-preview.png'), fullPage: true, animations: 'disabled' })
  await management.getByRole('button', { name: '取消' }).click()
  await page.getByRole('button', { name: '清空监测设备', exact: true }).click()
  management = page.getByRole('dialog', { name: '清空监测设备' })
  await expect(management).toContainText('不删除设备管理资产')
  await page.screenshot({ path: testInfo.outputPath('heartbeat-06-clear-confirmation.png'), fullPage: true, animations: 'disabled' })
  await management.getByRole('button', { name: '取消' }).click()
  expect(applied).toEqual([])
  await page.locator('.heartbeat-page .mr-card').first().click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: '综合监测', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('heartbeat-02-context-menu.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('menuitem', { name: '综合监测', exact: true }).click()
  const drawer = page.locator('.mr-monitor-drawer')
  await expect(drawer).toContainText('AP 综合动态监测')
  await expect(drawer.locator('canvas')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('heartbeat-03-monitoring-drawer.png'), fullPage: true, animations: 'disabled' })
  await drawer.getByRole('button', { name: 'Mesh', exact: true }).click()
  await drawer.locator('.mesh-event').click()
  await expect(drawer.locator('.raw-detail')).toContainText('Synthetic WMESH')
  await page.screenshot({ path: testInfo.outputPath('heartbeat-04-mesh-provenance.png'), fullPage: true, animations: 'disabled' })
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(drawer).toHaveCount(0)
  expect(errors).toEqual([])
  expect(unexpected).toEqual([])
})
