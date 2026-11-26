import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const cdpUrl = process.env.NETCONSOLE_CONSOLE_CDP || 'http://127.0.0.1:9333'
const rendererUrl = process.env.NETCONSOLE_CONSOLE_RENDERER || 'http://127.0.0.1:5179'
const scriptDir = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(scriptDir, '../../../..')
const highlightRules = JSON.parse(await readFile(resolve(repositoryRoot, 'src/netconsole/resources/terminal_rules/highlight_rules.json'), 'utf8'))
const dangerousRules = JSON.parse(await readFile(resolve(repositoryRoot, 'src/netconsole/resources/terminal_rules/dangerous_command_rules.json'), 'utf8'))
const outputRoot = resolve(
  process.env.NETCONSOLE_CONSOLE_CAPTURE_ROOT
    || resolve(scriptDir, '../../../../../reports/tests/console-r2'),
)

const devices = [
  { device_uuid: '11111111-1111-4111-8111-111111111111', name: 'LAB-CORE-SW-01', system_name: 'LAB-CORE-SW-01', primary_address: '192.0.2.10', station: '实验站', group_name: '核心交换', device_vendor: 'H3C', connection_status: 'REACHABLE', capabilities: { ssh: true, telnet: false } },
  { device_uuid: '22222222-2222-4222-8222-222222222222', name: 'LAB-ACCESS-SW-02', system_name: 'LAB-ACCESS-SW-02', primary_address: '192.0.2.20', station: '实验站', group_name: '接入交换', device_vendor: 'H3C', connection_status: 'REACHABLE', capabilities: { ssh: true, telnet: true } },
  { device_uuid: '33333333-3333-4333-8333-333333333333', name: 'LAB-AC-01', system_name: 'LAB-AC-01', primary_address: '192.0.2.30', station: '实验站', group_name: '无线控制器', device_vendor: 'H3C', connection_status: 'UNKNOWN', capabilities: { ssh: true, telnet: false } },
]
const sessions = []
const sftpSession = {
  session_id: 'visual-sftp-session',
  device_uuid: devices[1].device_uuid,
  device_name: devices[1].name,
  site_id: 'visual-fixture',
  site_name: '视觉验收',
  root_path: '/',
  current_path: '/',
  state: 'CONNECTED',
  created_at_ms: Date.now(),
  error_code: '',
}
const sftpEntries = [
  { name: 'startup.cfg', remote_path: '/startup.cfg', size: 18432, modified_time: '2026-11-23 04:50:00', category: 'config', is_dir: false, file_type: 'file', permissions: '-rw-r--r--' },
  { name: 'logfile', remote_path: '/logfile', size: null, modified_time: '2026-11-23 04:48:00', category: 'directory', is_dir: true, file_type: 'directory', permissions: 'drwxr-xr-x' },
]
const sftpTransfers = [
  { task_id: 'visual-transfer', session_id: sftpSession.session_id, kind: 'DOWNLOAD', source: '/startup.cfg', target: 'startup.cfg', status: 'COMPLETED', transferred_bytes: 18432, total_bytes: 18432, bytes_per_second: 921600, created_at_ms: Date.now(), started_at_ms: Date.now(), ended_at_ms: Date.now(), error_code: '', error_message: '', result_name: 'startup.cfg' },
]

function snapshot(device, index) {
  const now = Date.now()
  return {
    session_id: `${index}`.padStart(32, 'a'),
    device_uuid: device.device_uuid,
    device_name: device.name,
    site_id: 'visual-fixture',
    site_name: '视觉验收',
    protocol: 'SSH',
    encoding: 'utf-8',
    mode: 'INTERACTIVE',
    state: 'RUNNING',
    address: device.primary_address,
    port: 22,
    created_at_ms: now,
    updated_at_ms: now,
    connected_at_ms: now,
    ended_at_ms: null,
    disconnect_reason: '',
    error_code: '',
    command_count: 0,
    output_bytes: 0,
    recording_status: 'RECORDING',
    recording_sha256: '',
    recording_dropped_events: 0,
    manual_log_status: 'STOPPED',
    manual_log_id: '',
    manual_log_format: '',
    manual_log_filename: '',
    manual_log_dropped_events: 0,
    automation_write_active: index === 1,
    automation_write_task_id: index === 1 ? 'visual-write-task' : '',
    automation_write_task_name: index === 1 ? '视觉验收配置任务' : '',
  }
}

const terminalSettings = {
  schema_version: 1,
  font_family: 'Consolas',
  font_size: 14,
  foreground: '#d7e0ea',
  background: '#0d1117',
  cursor_color: '#55d6be',
  encoding: 'utf-8',
  automatic_recording: true,
  automatic_log_retention_days: 30,
  automatic_log_max_bytes: 1073741824,
  manual_log_recent_directory: '',
  dangerous_command_warning: true,
}

const browser = await chromium.connectOverCDP(cdpUrl)
const context = browser.contexts()[0]
const page = context.pages().find((candidate) => candidate.url().includes('127.0.0.1')) || context.pages()[0]
const runtimeErrors = []
page.on('pageerror', (error) => runtimeErrors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`)
})

await page.addInitScript(() => {
  class FixtureWebSocket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSING = 2
    static CLOSED = 3
    constructor() {
      this.readyState = FixtureWebSocket.CONNECTING
      this.listeners = new Map()
      setTimeout(() => {
        this.readyState = FixtureWebSocket.OPEN
        this.emit('open', {})
        this.emit('message', { data: JSON.stringify({ type: 'output', data: '\r\n<LAB-SW> display version\r\nH3C Comware Software, Version 7.1\r\n<LAB-SW>' }) })
      }, 20)
    }
    addEventListener(name, listener) {
      const values = this.listeners.get(name) || []
      values.push(listener)
      this.listeners.set(name, values)
    }
    emit(name, event) {
      for (const listener of this.listeners.get(name) || []) listener(event)
    }
    send() {}
    close() {
      this.readyState = FixtureWebSocket.CLOSED
      this.emit('close', {})
    }
  }
  window.WebSocket = FixtureWebSocket
})

await page.route('**/*', async (route) => {
  const request = route.request()
  const url = new URL(request.url())
  if (url.pathname === '/api/device-management/devices') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: devices, total: devices.length }) })
    return
  }
  if (url.pathname === '/api/terminal/profiles') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ schema_version: 1, folders: [], profiles: [] }) })
    return
  }
  if (url.pathname === '/api/terminal/settings') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(terminalSettings) })
    return
  }
  if (url.pathname === '/api/terminal/rules/highlight') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(highlightRules) })
    return
  }
  if (url.pathname === '/api/terminal/rules/dangerous') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dangerousRules) })
    return
  }
  if (url.pathname === '/api/terminal/sftp/sessions' && request.method() === 'POST') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sftpSession) })
    return
  }
  if (url.pathname === '/api/terminal/sftp/sessions' && request.method() === 'GET') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) })
    return
  }
  if (/\/api\/terminal\/sftp\/sessions\/.+\/entries$/.test(url.pathname)) {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: sftpSession, path: '/', items: sftpEntries }) })
    return
  }
  if (url.pathname === '/api/terminal/sftp/transfers') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: sftpTransfers, total: sftpTransfers.length }) })
    return
  }
  if (/\/api\/terminal\/sftp\/sessions\/.+$/.test(url.pathname) && request.method() === 'DELETE') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...sftpSession, state: 'CLOSED' }) })
    return
  }
  if (url.pathname === '/api/terminal/sessions' && request.method() === 'POST') {
    const payload = request.postDataJSON()
    const device = devices.find((item) => item.device_uuid === payload.device_uuid)
    const session = snapshot(device, sessions.length + 1)
    sessions.push(session)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session, ticket: `ticket-${sessions.length}`, ticket_expires_at_ms: Date.now() + 30_000 }) })
    return
  }
  if (url.pathname === '/api/terminal/sessions' && request.method() === 'GET') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: sessions, total: sessions.length }) })
    return
  }
  if (url.pathname === '/api/terminal/history') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: sessions, total: sessions.length }) })
    return
  }
  if (/\/api\/terminal\/history\/.+\/events$/.test(url.pathname)) {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ at_ms: Date.now(), event_type: 'OUTPUT', data: '<LAB-SW> display version\nH3C Comware Software, Version 7.1\n<LAB-SW>' }], has_more: false }) })
    return
  }
  if (/\/api\/terminal\/sessions\/.+\/ticket$/.test(url.pathname)) {
    const sessionId = url.pathname.split('/').at(-2)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ticket: 'reconnect-ticket', session_id: sessionId, ticket_expires_at_ms: Date.now() + 30_000 }) })
    return
  }
  await route.continue()
})

await mkdir(outputRoot, { recursive: true })
await page.setViewportSize({ width: 1920, height: 1080 })
await page.goto(`${rendererUrl}/?netconsole_host=electron`, { waitUntil: 'domcontentloaded' })
const consoleMenuItem = page.locator('.app-menu .el-menu-item').filter({ hasText: '设备控制台' }).first()
await consoleMenuItem.waitFor()
await page.waitForFunction(() => {
  const items = [...document.querySelectorAll('.app-menu .el-menu-item')]
  const item = items.find((candidate) => candidate.textContent?.trim() === '设备控制台')
  return Boolean(item && !item.classList.contains('is-disabled'))
})
await consoleMenuItem.click()
await page.locator('.console-workspace').waitFor()
const rows = page.locator('.device-row')
await rows.nth(0).dblclick()
await page.locator('.terminal-tab').waitFor()
await rows.nth(1).dblclick()
await page.getByRole('button', { name: '分屏' }).click()
await page.getByText('左右分屏', { exact: true }).click()
await page.waitForTimeout(300)
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1920x1080.png'), fullPage: false, animations: 'disabled' })
await page.getByRole('button', { name: '显示按钮栏' }).click()
await page.locator('.mapped-button-bar button').first().waitFor()
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1920x1080-button-bar.png'), fullPage: false, animations: 'disabled' })

await page.setViewportSize({ width: 2560, height: 1440 })
await page.getByRole('button', { name: '会话记录' }).click()
await page.waitForTimeout(300)
await page.screenshot({ path: resolve(outputRoot, 'console-electron-2560x1440-history.png'), fullPage: false, animations: 'disabled' })

await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
await page.setViewportSize({ width: 1024, height: 680 })
await page.waitForTimeout(300)
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1024x680.png'), fullPage: false, animations: 'disabled' })
const toolbar = page.locator('.console-toolbar')
await toolbar.evaluate((element) => element.scrollTo({ left: element.scrollWidth, behavior: 'instant' }))
await page.getByTitle('终端设置').waitFor()
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1024x680-toolbar-end.png'), fullPage: false, animations: 'disabled' })

await page.setViewportSize({ width: 1920, height: 1080 })
if (process.env.NETCONSOLE_SKIP_SFTP !== '1') {
  await page.getByRole('button', { name: 'SFTP' }).click()
  await page.getByRole('button', { name: '连接 SFTP' }).click()
  await page.locator('.sftp-panel .el-table .cell').filter({ hasText: /^startup\.cfg$/ }).first().waitFor()
  await page.screenshot({ path: resolve(outputRoot, 'console-electron-1920x1080-sftp.png'), fullPage: false, animations: 'disabled' })
  await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
}
await page.getByTitle('终端设置').click()
const settingsDialog = page.getByRole('dialog', { name: '终端设置' })
const settingsOpenMs = []
await settingsDialog.waitFor()
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1920x1080-settings.png'), fullPage: false, animations: 'disabled' })
for (let index = 0; index < 30; index += 1) {
  await settingsDialog.getByRole('button', { name: '取消' }).click()
  await settingsDialog.waitFor({ state: 'detached' })
  const startedAt = Date.now()
  await page.getByTitle('终端设置').click()
  await settingsDialog.waitFor()
  settingsOpenMs.push(Date.now() - startedAt)
}
await settingsDialog.getByRole('button', { name: '取消' }).click()
const settingsPerformanceMeasures = await page.evaluate(() => performance.getEntriesByType('measure')
  .filter(entry => entry.name.startsWith('console.settings.'))
  .map(entry => ({ name: entry.name, duration_ms: Math.round(entry.duration) })))
const rendererLongTaskMs = await page.evaluate(() => performance.getEntriesByType('longtask')
  .reduce((total, entry) => total + entry.duration, 0))

await page.getByRole('button', { name: '新建 COM 会话' }).click()
const serialDialog = page.getByRole('dialog', { name: '新建 COM 串口会话' })
await serialDialog.waitFor()
await serialDialog.getByRole('button', { name: '刷新串口列表' }).click()
await page.locator('.serial-form .el-select').first().click()
await page.locator('.el-select-dropdown:visible').waitFor()
const serialOptions = await page.locator('.el-select-dropdown:visible').innerText()
const serialDialogText = await serialDialog.innerText()
if (!serialDialogText.includes('H3C Console') || !serialDialogText.includes('9600') || !serialDialogText.includes('8')) {
  throw new Error('H3C serial defaults are missing from the real Electron dialog')
}
await page.screenshot({ path: resolve(outputRoot, 'console-electron-1920x1080-serial.png'), fullPage: false, animations: 'disabled' })
await serialDialog.getByRole('button', { name: '取消' }).click()

await writeFile(resolve(outputRoot, 'serial-electron-evidence.json'), JSON.stringify({
  settings_reopen_cycles: 30,
  settings_open_ms: {
    samples: settingsOpenMs,
    min: Math.min(...settingsOpenMs),
    median: [...settingsOpenMs].sort((left, right) => left - right)[Math.floor(settingsOpenMs.length / 2)],
    max: Math.max(...settingsOpenMs),
  },
  settings_performance_measures: settingsPerformanceMeasures,
  renderer_long_task_total_ms: Math.round(rendererLongTaskMs),
  serial_defaults: 'H3C Console, 9600 8N1, no flow control, DTR/RTS KEEP',
  enumerated_ports: serialOptions.split('\n'),
  serial_hardware_opened: false,
}, null, 2) + '\n', 'utf8')
console.log(`Console Electron acceptance PASS: settings reopen 30x median=${[...settingsOpenMs].sort((left, right) => left - right)[Math.floor(settingsOpenMs.length / 2)]}ms range=${Math.min(...settingsOpenMs)}-${Math.max(...settingsOpenMs)}ms, serial defaults H3C 9600 8N1, ports=${serialOptions.split('\n').join(',')}`)

if (runtimeErrors.length) {
  throw new Error(`Electron Console runtime errors:\n${runtimeErrors.join('\n')}`)
}

process.exit(0)
