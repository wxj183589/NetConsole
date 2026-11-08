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

async function mockGround(page: Page) {
  const requests: URL[] = []
  const unexpected: string[] = []
  const starts: Array<Record<string, unknown>> = []
  let quick: Record<string, any> | null = null
  let conflict = false
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const url = new URL(request.url())
    requests.push(url)
    const path = url.pathname
    const method = request.method()
    const paged = (items: unknown[], total = items.length) => ({ items, total, page: Number(url.searchParams.get('page') || 1), page_size: Number(url.searchParams.get('page_size') || 100), total_exact: true })
    let body: unknown
    if (path === '/api/features') body = { items: [
      ...['overview', 'heartbeat', 'ac_mesh_link', 'quick_ping', 'syslog', 'deep', 'timeline', 'health', 'archives', 'settings'].map(key => `ground_unattended.${key}`),
      'capability.ground_unattended.quick_ping', 'capability.ground_unattended.history_export',
    ].map(feature_id => ({ feature_id, visible: true, enabled: true })) }
    else if (path === `${root}/status`) body = {
      ...run, site_id: profile.site_id, enabled: true, service_state: 'RUNNING', paused: false, running_mode: 'LIGHTWEIGHT',
      active_run_id: run.run_id, active_run_state: 'RUNNING', active_run_date: run.run_date,
      latest_run_id: run.run_id, latest_run_date: run.run_date, latest_run_state: 'RUNNING',
      schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: profile.timezone,
      ping_target_count: 3, mainline_train_count: 1, active_deep_train_count: 0,
    }
    else if (path === `${root}/profile`) body = profile
    else if (path === `${root}/runs`) body = paged([run])
    else if (path === `${root}/trains`) body = paged([train])
    else if (path === `${root}/health`) body = health
    else if (path === `${root}/heartbeat`) body = heartbeat
    else if (path.includes('/operations/')) body = null
    else if (path === `${root}/ping-targets`) body = paged(heartbeat.mrs.flatMap(mr => mr.ip_states.map(ip => ({
      ...ip, run_id: run.run_id, train_id: train.train_id, train_no: train.train_no, mr_id: mr.mr_uuid,
      mr_name: mr.mr_name, mr_position_code: mr.role, target_ip: ip.ip, query_identity: ip.ip,
      loss_rate_percent: 1.67, station: '', section: '', success_count: 59,
      continuous_loss_max_count: 1, continuous_loss_max_seconds: 1,
    }))))
    else if (path === `${root}/timeline`) {
      const start = (Number(url.searchParams.get('page') || 1) - 1) * 100
      body = paged(Array.from({ length: 100 }, (_, index) => ({
        event_id: start + index + 1, run_id: run.run_id, ts: now, device_time: now, received_at: now,
        train_id: train.train_id, train_no: train.train_no, mr_name: '合成 MR CT', mr_id: endpoints[0]!.mr_id,
        event_type: 'mr_recovered', title: `合成恢复事件 ${start + index + 1}`, message: 'HTTP Mock 事件，保留设备与接收时间', severity: 'info', details: {},
      })), 205)
    } else if (path === `${root}/syslog-records`) {
      const start = (Number(url.searchParams.get('page') || 1) - 1) * 100
      body = { ...paged(Array.from({ length: 100 }, (_, index) => ({
        raw_file_id: 'mock-raw', raw_line_number: start + index + 1, receive_time: now, device_time: now,
        train_id: train.train_id, train_no: train.train_no, mr_name: '合成 MR CT', mr_id: endpoints[0]!.mr_id,
        mr_role: 'CT', source_ip: '192.0.2.10', system_name: 'MOCK-CT', facility: 'WMESH', severity: 'info',
        event_type: 'MESH_LINKUP', event_family: 'WMESH', identity_status: 'VERIFIED',
        raw_text: `Synthetic Syslog ${start + index + 1} ${'X'.repeat(300)}`, data_source: 'ACTIVE', raw_file_status: 'OPEN',
      })), 205), diagnostics }
    } else if (path === `${root}/syslog-transport-status`) body = {
      configured_return_ip: '127.0.0.1', configured_return_port: 5514, listen_host: '127.0.0.1', listen_port: 5514,
      receiver_running: true, receiver_state: 'RUNNING', port_state: 'LISTENING', ports_match: true,
      received_count: 20000, queue_length: 0, queue_capacity: 20000, dropped_count: 0,
      return_address_status: 'LOCAL_ADDRESS', return_address_is_local: true,
    }
    else if (path === `${root}/quick-ping` && method === 'POST') {
      const payload = request.postDataJSON() as Record<string, any>
      if (conflict) { await route.fulfill({ status: 409, json: { detail: { code: 'QUICK_PING_DUPLICATE_ACTIVE', message: 'IP 192.0.2.10 已由活动任务 concurrent-owner 占用' } } }); return }
      starts.push(payload)
      quick = { run_id: 'mock-quick-1', state: 'RUNNING', started_at: now, ended_at: '', config: payload,
        targets: payload.targets, stats,
        target_stats: Object.fromEntries(payload.targets.map((target: any) => [target.target_ip, { ...stats, current_rtt_ms: 2.5 }])),
        target_runtime: Object.fromEntries(payload.targets.map((target: any) => [target.target_ip, { state: 'RUNNING', started_at: now }])), error: '', raw_files: [] }
      body = quick
    } else if (path === `${root}/quick-ping`) body = { ...paged(quick ? [quick] : []), active_ips: quick?.state === 'RUNNING' ? Object.fromEntries(quick.targets.filter((target: any) => quick!.target_runtime[target.target_ip].state === 'RUNNING').map((target: any) => [target.target_ip, quick!.run_id])) : {} }
    else if (path.includes('/targets/') && path.endsWith('/stop') && quick) {
      const ip = path.split('/targets/')[1]!.split('/')[0]!
      quick.target_runtime[ip].state = 'CANCELLED'; body = quick
    }
    else if (path.endsWith('/mock-quick-1/stop')) { quick = { ...quick, state: 'COMPLETED', ended_at: now }; body = quick }
    else if (path.endsWith('/mock-quick-1/samples')) body = {
      items: Array.from({ length: 20 }, (_, i) => ({ received_at: new Date(Date.parse(now) + i * 200).toISOString(), target_ip: '192.0.2.10', sample: { ok: i % 10 !== 0, rtt_ms: i % 10 !== 0 ? 2 + i / 10 : null } })), next_cursor: '', scan_budget_exhausted: false,
    }
    else if (path.endsWith('/quick-ping/mock-quick-1')) body = quick
    else if (path === `${root}/deep-collections` || path === `${root}/archives`) body = paged([])
    else if (path === `${root}/history`) body = { ...paged([]), sources: {} }
    else if (path.endsWith('/ipv4-addresses')) body = paged([])
    else if (path.endsWith('/online-mr-control/presets')) body = { ping: [], traffic: [] }
    else if (path.endsWith('/train-online/controllers')) body = []
    else if (path === '/api/ac-management/mesh-links/summary') body = { data_status: 'stale', registered_mrs: 2, online_mrs: 2, age_seconds: 31 }
    else if (path === '/api/ac-management/mesh-links/raw-tail') body = { available: false, lines: [] }
    else if (path.startsWith('/api/ac-management/mesh-links/')) body = paged([])
    else { unexpected.push(`${method} ${path}`); await route.fulfill({ status: 404, json: { detail: 'Unmocked API' } }); return }
    await route.fulfill({ json: body })
  })
  return { requests, unexpected, starts, setConflict: (value: boolean) => { conflict = value } }
}

test('Quick Ping multi-IP selection, occupancy, conflict and independent statistics', async ({ page }, testInfo) => {
  const api = await mockGround(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/tests/visual/ground.html?netconsole_host=electron')
  await page.getByRole('tab', { name: '快速 Ping', exact: true }).click()
  const quick = page.locator('.quick-ping-page')
  const select = quick.locator('.target-select')
  await select.click()
  for (const ip of ['192.0.2.10', '192.0.2.20', '192.0.2.11']) {
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: ip }).click()
  }
  await page.keyboard.press('Escape')
  await expect(quick.locator('.selected-targets')).toContainText('已选 IP: 3')
  await page.screenshot({ path: testInfo.outputPath('quick-01-multiple-mr-selection.png'), fullPage: true, animations: 'disabled' })
  await quick.getByRole('button', { name: '开始', exact: true }).click()
  await expect(quick.locator('.status-line')).toContainText('RUNNING')
  expect((api.starts[0]!.targets as unknown[]).length).toBe(3)
  await expect(quick.locator('.detail')).toContainText('192.0.2.20')
  await page.screenshot({ path: testInfo.outputPath('quick-02-same-mr-primary-backup.png'), fullPage: true, animations: 'disabled' })
  await select.click()
  await expect(page.locator('.el-select-dropdown__item:visible').filter({ hasText: '192.0.2.10' })).toHaveClass(/is-disabled/)
  await expect(page.locator('.el-select-dropdown:visible')).toContainText('mock-quick-1')
  await page.screenshot({ path: testInfo.outputPath('quick-03-occupied-ips-disabled.png'), fullPage: true, animations: 'disabled' })
  await page.keyboard.press('Escape')
  await quick.locator('.detail .el-table').first().scrollIntoViewIfNeeded()
  await expect(quick.locator('.detail .el-table').first()).toContainText('2.50 ms')
  await page.screenshot({ path: testInfo.outputPath('quick-04-independent-ip-statistics.png'), fullPage: true, animations: 'disabled' })
  await quick.getByRole('button', { name: '停止此 IP', exact: true }).first().click()
  await expect(quick.locator('.detail .el-table').first()).toContainText('CANCELLED')
  await expect(quick.locator('.status-line')).toContainText('RUNNING')
  await page.screenshot({ path: testInfo.outputPath('quick-05-batch-with-one-ip-stopped.png'), fullPage: true, animations: 'disabled' })
  await quick.getByRole('button', { name: '停止当前任务', exact: true }).click()
  await expect(quick.locator('.status-line')).toContainText('COMPLETED')
  api.setConflict(true)
  await quick.getByRole('button', { name: '开始', exact: true }).click()
  await expect(quick.locator('.el-alert').first()).toContainText('concurrent-owner')
  await page.screenshot({ path: testInfo.outputPath('quick-06-concurrent-ip-conflict.png'), fullPage: true, animations: 'disabled' })
  expect(errors).toEqual([])
  expect(api.unexpected).toEqual([])
})
