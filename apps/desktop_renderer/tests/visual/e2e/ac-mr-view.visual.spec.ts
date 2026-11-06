import { expect, test, type Page } from '@playwright/test'

// Synthetic HTTP data drives the real GroundUnattendedView and AC MR components.
const root = '/api/rail-transit/ground-unattended'
const mesh = '/api/ac-management/mesh-links'
const now = '2026-11-07T09:00:00+08:00'
const later = '2026-11-07T09:01:00+08:00'
const paged = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 50 })

const peer = (id: number, mr: string, ap: string, rssi: number, status = 'current') => ({
  id, snapshot_id: 41, controller_id: 'ac-1', controller_name: '合成 AC', mr_id: mr,
  train_no: '001', car_end: mr.endsWith('ct') ? 'CT' : 'CW', mr_name: mr.endsWith('ct') ? '合成 MR CT' : '合成 MR CW',
  mr_mac: mr.endsWith('ct') ? '00:11:22:33:44:10' : '00:11:22:33:44:11', mr_device_id: mr,
  mr_management_ip: mr.endsWith('ct') ? '192.0.2.10' : '192.0.2.11', mr_online_status: 'online',
  peer_ap_id: `ap-${ap}`, peer_ap_name: `区间 AP ${ap}`, peer_ap_mac: `00:aa:bb:cc:dd:${String(id).padStart(2, '0')}`,
  bssid: `02:aa:bb:cc:dd:${String(id).padStart(2, '0')}`, peer_radio: '5G', mesh_interface: 'WLAN-MESH',
  rssi, station: '合成站', section: '合成区间', mileage: '', line_side: '', ap_rx_power: '', switch_rx_power: '',
  last_seen_at: now, device_time: now, received_at: later, match_method: 'mac', match_warning: '',
  data_status: status === 'current' ? 'fresh' : 'stale', relation_status: status, source_type: 'AC_SNAPSHOT',
})
const ctPeers = [peer(1, 'mr-ct', '01', -55), peer(2, 'mr-ct', '02', -62), peer(3, 'mr-ct', '03', -70, 'stale')]
const cwPeers = [peer(4, 'mr-cw', '01', -64)]
const links = [...ctPeers, ...cwPeers]
const mr = (role: 'CT' | 'CW') => ({
  mr_id: `mr-${role.toLowerCase()}`, train_no: '001', train_display_name: '合成列车 001', car_end: role,
  mr_name: `合成 MR ${role}`, mr_mac: role === 'CT' ? '00:11:22:33:44:10' : '00:11:22:33:44:11',
  mr_device_id: `mr-${role.toLowerCase()}`, management_ip: role === 'CT' ? '192.0.2.10' : '192.0.2.11',
  management_ips: role === 'CT' ? ['192.0.2.10', '192.0.2.20'] : ['192.0.2.11'],
  online_status: 'online', peer_ap_id: 'ap-01', peer_ap_name: '区间 AP 01', peer_ap_mac: '00:aa:bb:cc:dd:01',
  mesh_radio: '5G', rssi: -55, station: '', section: '', mileage: '', line_side: '', ap_rx_power: '', switch_rx_power: '',
  last_seen_at: now, device_time: now, received_at: later, match_method: 'mac', match_warning: '', data_status: 'fresh',
  peer_aps: role === 'CT' ? ctPeers : cwPeers, resolved_ap: `车载 AP ${role}`, resolved_ap_station: '车辆段',
  resolved_ap_section: '', identity_status: 'verified',
})
const mrs = [mr('CT'), mr('CW')]
const summary = {
  site_id: 'synthetic', controller_id: 'ac-1', controller_name: '合成 AC', registered_mrs: 2,
  online_mrs: 2, offline_mrs: 0, stale_mrs: 0, unknown_mrs: 0, abnormal_mrs: 1,
  active_links: 3, link_total: 4, unmatched_links: 0, offline_ap_links: 0, unique_peer_aps: 3,
  updated_at: later, device_time: now, received_at: later, age_seconds: 60,
  data_status: 'fresh', source_type: 'AC_SNAPSHOT', raw_available: true, message: '',
}

async function mockApi(page: Page) {
  const unexpected: string[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let body: unknown
    if (path === '/api/features') body = { items: ['overview', 'heartbeat', 'ac_mesh_link', 'quick_ping', 'syslog', 'deep', 'timeline', 'health', 'archives', 'settings'].map(key => ({ feature_id: `ground_unattended.${key}`, visible: true, enabled: true })) }
    else if (path === `${root}/status`) body = { site_id: 'synthetic', enabled: true, service_state: 'RUNNING', paused: false, running_mode: 'LIGHTWEIGHT', active_run_id: 'synthetic-run', active_run_state: 'RUNNING', active_run_date: '2026-11-07', latest_run_id: 'synthetic-run', latest_run_date: '2026-11-07', latest_run_state: 'RUNNING', schedule_start_time: '07:00', schedule_end_time: '23:00', timezone: 'Asia/Shanghai', ping_target_count: 2, mainline_train_count: 1, active_deep_train_count: 0 }
    else if (path === `${root}/profile`) body = { site_id: 'synthetic', enabled: true, deep_fping: { enabled: false, target: '', preset_key: '', preset_name: '', packet_size: 64, interval_ms: 100, timeout_ms: 1000, loss_warn_percent: 1, latency_warn_ms: 100 }, deep_collection_master_enabled: false }
    else if (path === `${root}/runs`) body = paged([{ run_id: 'synthetic-run', run_date: '2026-11-07', state: 'RUNNING', data_availability: 'ACTIVE_RAW', actual_started_at: now }])
    else if (path === `${root}/health`) body = { site_id: 'synthetic', status: 'HEALTHY', supervisor_running: true, run_state: 'RUNNING' }
    else if (path === `${root}/heartbeat`) body = { run_id: 'synthetic-run', run_state: 'RUNNING', mr_counts: { ONLINE: 2 }, train_counts: { BOTH_ONLINE: 1 }, mrs: [], trains: [] }
    else if (path === `${root}/trains` || path === `${root}/ping-targets` || path === `${root}/quick-ping` || path === `${root}/deep-collections` || path === `${root}/archives` || path === `${root}/timeline`) body = paged([])
    else if (path === `${root}/history`) body = { ...paged([]), sources: {} }
    else if (path === `${root}/syslog-transport-status`) body = { receiver_running: true, receiver_state: 'RUNNING', port_state: 'LISTENING', ports_match: true }
    else if (path === `${mesh}/summary`) body = summary
    else if (path === `${mesh}/current`) body = paged(links)
    else if (path === `${mesh}/mrs`) body = paged(mrs)
    else if (path === `${mesh}/mrs/mr-ct` || path === `${mesh}/mrs/mr-cw`) {
      const selected = path.endsWith('mr-ct') ? mrs[0]! : mrs[1]!
      const current = selected.peer_aps
      const history = current.flatMap((item, index) => [
        { ...item, id: item.id + 100, snapshot_id: 39, rssi: item.rssi - 4, device_time: '2026-11-07T08:58:00+08:00' },
        { ...item, id: item.id + 200, snapshot_id: 40, rssi: item.rssi - 2, device_time: `2026-11-07T08:59:0${index}+08:00` },
      ])
      body = { mr: selected, current_links: current, recent_events: [{ id: 1, event_time: now, event_type: 'MESH_LINKUP', status: 'current', station: '合成站', ap_name: '区间 AP 01', rssi: -55, car_end: selected.car_end }], history_links: history, history_total: history.length, history_page: 1, history_page_size: 100, history_note: '仅显示真实快照观测点。' }
    }
    else if (path === `${mesh}/peer-aps`) body = paged(['01', '02', '03'].filter(ap => !url.searchParams.get('query') || links.some(link => link.peer_ap_name === `区间 AP ${ap}` && `${link.peer_ap_mac}${link.bssid}${link.peer_ap_name}`.includes(url.searchParams.get('query')!))).map(ap => ({ ap_key: `ap-${ap}`, ap_name: `区间 AP ${ap}`, mac: links.find(link => link.peer_ap_name === `区间 AP ${ap}`)!.peer_ap_mac, bssids: links.filter(link => link.peer_ap_name === `区间 AP ${ap}`).map(link => link.bssid), station: '合成站', section: '合成区间', relations: links.filter(link => link.peer_ap_name === `区间 AP ${ap}`) })))
    else if (path === `${mesh}/snapshots`) body = paged([])
    else if (path === `${mesh}/raw-tail`) body = { snapshot_id: 41, available: false, lines: [], line_count: 0, source_reference: '', updated_at: later, message: '' }
    else if (path.endsWith('/ipv4-addresses')) body = paged([])
    else if (path.endsWith('/online-mr-control/presets')) body = { ping: [], traffic: [] }
    else if (path.endsWith('/train-online/controllers')) body = [{ controller_id: 'ac-1', name: '合成 AC', primary_address: '192.0.2.1', connection_ready: true }]
    else if (path.includes('/operations/')) body = null
    else { unexpected.push(`${route.request().method()} ${path}`); await route.fulfill({ status: 404, json: { detail: 'Unmocked API' } }); return }
    await route.fulfill({ json: body })
  })
  return unexpected
}

test('AC MR CT/CW multi-AP, reverse AP, graph and RSSI detail', async ({ page }, testInfo) => {
  const unexpected = await mockApi(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/tests/visual/ground.html?netconsole_host=electron')
  await page.getByRole('tab', { name: 'AC-Mesh-Link', exact: true }).click()
  const meshPage = page.locator('.mesh-page')
  await expect(meshPage.locator('.mr-row')).toHaveCount(2)
  await expect(meshPage.locator('.mr-row').first()).toContainText('区间 AP · 3')
  await expect(meshPage.locator('.mr-row').first()).toContainText('192.0.2.20')
  await expect(meshPage.locator('.mr-row').last()).toContainText('区间 AP · 1')
  await page.screenshot({ path: testInfo.outputPath('ac-01-mr-ct-cw-multi-ap.png'), fullPage: true })

  await meshPage.getByText('区间 AP 视图', { exact: true }).click()
  await expect(meshPage.locator('.ap-card')).toHaveCount(3)
  await expect(meshPage.locator('.ap-card').first()).toContainText('2 MR')
  await meshPage.locator('.ap-card').first().click()
  await expect(page.locator('.el-drawer:visible')).toContainText('合成 MR CT')
  await expect(page.locator('.el-drawer:visible')).toContainText('合成 MR CW')
  await page.screenshot({ path: testInfo.outputPath('ac-02-ap-reverse-drawer.png'), fullPage: true })
  await page.locator('.el-drawer:visible .el-drawer__close-btn').click()

  await meshPage.getByText('连接关系图', { exact: true }).click()
  await expect(meshPage.locator('.relation-edge')).toHaveCount(4)
  await expect(meshPage.locator('.relation-edge.uncertain')).toHaveCount(1)
  await expect(meshPage.locator('.graph-observations button')).toHaveCount(4)
  await page.screenshot({ path: testInfo.outputPath('ac-03-relationship-graph.png'), fullPage: true })

  await meshPage.getByText('车载 MR 视图', { exact: true }).click()
  await meshPage.locator('.mr-row').first().getByRole('button', { name: '+1' }).click()
  const drawer = page.locator('.el-drawer:visible')
  await expect(drawer).toContainText('当前快照关联 (3)')
  await expect(drawer.locator('.ac-rssi-chart canvas')).toBeVisible()
  await expect(drawer).toContainText('区间 AP 03')
  await page.screenshot({ path: testInfo.outputPath('ac-04-multi-peer-rssi-drawer.png'), fullPage: true })
  expect(errors).toEqual([])
  expect(unexpected).toEqual([])
})
