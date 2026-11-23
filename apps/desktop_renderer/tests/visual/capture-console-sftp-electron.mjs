import { _electron } from '@playwright/test'
import { createRequire } from 'node:module'
import { spawn, execFileSync } from 'node:child_process'
import { randomBytes, createHash } from 'node:crypto'
import { mkdir, mkdtemp, writeFile, readFile, copyFile, readdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const workspace = resolve(repository, repository.replaceAll('\\', '/').includes('/worktrees/') ? '../..' : '..')
const electronRoot = resolve(repository, 'apps/desktop_electron')
const require = createRequire(resolve(electronRoot, 'package.json'))
const { build } = require('esbuild')
const output = resolve(workspace, 'reports/build/release-v1.5.18-20261123/electron')
await mkdir(output, { recursive: true })
const runRoot = await mkdtemp(resolve(workspace, 'test-data/NetConsole/console-sftp-electron-'))
const dataRoot = resolve(runRoot, 'data')
await mkdir(dataRoot, { recursive: true })
const appRoot = resolve(runRoot, 'apps/desktop_electron')
await mkdir(appRoot, { recursive: true })
await mkdir(resolve(runRoot, 'resources/branding'), { recursive: true })
await copyFile(resolve(repository, 'resources/branding/netconsole.ico'), resolve(runRoot, 'resources/branding/netconsole.ico'))
await writeFile(resolve(appRoot, 'package.json'), JSON.stringify({ name: 'netconsole-sftp-acceptance', version: JSON.parse(await readFile(resolve(electronRoot, 'package.json'), 'utf8')).version, main: 'main/index.cjs' }))
// Build into a new isolated app; no cleanup/build script touches existing dist.
for (const entry of ['main', 'preload']) await build({ entryPoints: [resolve(electronRoot, `src/${entry}/index.ts`)], outfile: resolve(appRoot, `${entry}/index.cjs`), bundle: true, platform: 'node', format: 'cjs', target: 'node24', external: ['electron'] })
const token = randomBytes(32).toString('hex')
const env = { ...process.env, NETCONSOLE_PROJECT_ROOT: repository, NETCONSOLE_PYTHON: resolve(repository, '.venv/Scripts/python.exe'), PYTHONPATH: resolve(repository, 'src'), NETCONSOLE_DATA_ROOT: dataRoot, NETCONSOLE_RUNTIME_ROOT: resolve(runRoot, 'runtime'), NETCONSOLE_RUNTIME_MODE: 'test', NETCONSOLE_STORAGE_MODE: 'isolated_test', NETCONSOLE_DEV_TEMP_DATA_ROOT: '1', NETCONSOLE_ISOLATED_SMOKE: '1', NETCONSOLE_DEV_MODE: '1', NETCONSOLE_DEV_BACKEND_PORT: '18021', NETCONSOLE_DEV_SESSION_TOKEN: token, NETCONSOLE_RENDERER_DEV_URL: 'http://127.0.0.1:5181', VITE_API_BASE: 'http://127.0.0.1:18021', VITE_DEV_SESSION_TOKEN: token }
delete env.ELECTRON_RUN_AS_NODE
let fixture, vite, app, page
const nativeDialog = process.env.NETCONSOLE_NATIVE_DIALOG === '1'
const evidence = { runRoot, tests: [], displays: [], resolutions: [], nativeDialog: nativeDialog ? 'actual Windows Save As with prefilled authorized test path' : 'NOT VERIFIED: path selection controlled; actual Main IPC and filesystem used' }
const api = async (path, body, method = body ? 'POST' : 'GET') => {
  const response = await fetch(`http://127.0.0.1:18021/api/terminal/${path}`, { method, headers: { 'X-NetConsole-Session': token, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}: ${await response.text()}`)
  return response.json()
}
try {
  fixture = spawn(env.NETCONSOLE_PYTHON, ['-m', 'scripts.dev.console_sftp_fixture'], { cwd: repository, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  await new Promise((done, reject) => {
    let received = ''
    const timeout = setTimeout(() => reject(new Error('fixture readiness timeout')), 20000)
    fixture.stdout.on('data', chunk => { received += chunk; if (received.includes('\n')) { clearTimeout(timeout); try { evidence.fixture = JSON.parse(received.trim().split('\n')[0]); done() } catch (error) { reject(error) } } })
    fixture.once('exit', code => { if (!received.includes('\n')) { clearTimeout(timeout); reject(new Error(`fixture exited ${code}`)) } })
    fixture.stderr.on('data', chunk => process.stderr.write(chunk))
  })
  const rendererRequire = createRequire(resolve(repository, 'apps/desktop_renderer/package.json'))
  const viteCli = resolve(dirname(rendererRequire.resolve('vite/package.json')), 'bin/vite.js')
  vite = spawn(process.execPath, [viteCli, '--host', '127.0.0.1', '--port', '5181', '--strictPort'], { cwd: resolve(repository, 'apps/desktop_renderer'), env, windowsHide: true, stdio: 'ignore' })
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await fetch('http://127.0.0.1:5181').then(r => r.ok).catch(() => false)) break
    await new Promise(done => setTimeout(done, 200))
  }
  app = await _electron.launch({ executablePath: require('electron'), args: [appRoot], cwd: repository, env, timeout: 60000 })
  page = await app.firstWindow()
  page.setDefaultTimeout(30000)
  page.on('pageerror', error => process.stderr.write(`renderer error: ${error.message}\n`))
  await page.waitForURL('http://127.0.0.1:5181/**', { timeout: 90000 })
  // Warm lazy routes before opening real sessions. Vite dependency discovery may
  // reload a development page; this is setup, outside the persistence assertions.
  await page.goto('http://127.0.0.1:5181/console')
  for (const path of ['/network/devices', '/ac-management/fit-aps', '/tasks', '/config-center', '/tools', '/console']) {
    await page.waitForFunction(() => Boolean(document.querySelector('#app')?.__vue_app__))
    const navigate = () => page.evaluate(async target => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target) }, path)
    try { await navigate() } catch (error) {
      if (!String(error).includes('Execution context was destroyed')) throw error
      await page.waitForFunction(() => Boolean(document.querySelector('#app')?.__vue_app__))
      await navigate()
    }
    await page.waitForLoadState('networkidle')
  }
  await page.locator('.device-row').filter({ hasText: 'LAB-SFTP-SW' }).dblclick()
  await page.locator('.xterm-screen').waitFor()
  await page.waitForFunction(() => document.querySelector('.xterm-screen')?.textContent?.includes('LAB-SFTP isolated server'))
  await page.locator('.xterm-helper-textarea').focus()
  await page.keyboard.type('display version')
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => document.querySelector('.xterm-screen')?.textContent?.includes('fixture interactive response'))
  if (!await page.locator('.sftp-panel').isVisible()) await page.getByRole('button', { name: 'SFTP', exact: true }).click()
  await page.locator('.sftp-panel').getByRole('button', { name: '连接 SFTP', exact: true }).click()
  await page.locator('.sftp-files tr').filter({ hasText: 'startup.cfg' }).waitFor()
  evidence.tests.push('real SSH shell and SFTP listing connected to isolated server')
  const row = page.locator('.sftp-files tr').filter({ hasText: 'startup.cfg' })
  await row.locator('input[type=checkbox]').check()
  await page.locator('.sftp-actions').getByRole('button', { name: '下载', exact: true }).click()
  await page.locator('.transfer-row').filter({ hasText: '待保存' }).waitFor()
  const taskHint = page.getByRole('button', { name: '关闭任务进度提示' })
  if (await taskHint.isVisible()) await taskHint.click()
  const target = resolve(runRoot, '中文设备配置.cfg')
  await app.evaluate(({ dialog }, options) => {
    if (options.native) {
      const original = dialog.showSaveDialog.bind(dialog)
      dialog.showSaveDialog = (window, settings) => original(window, { ...settings, defaultPath: options.target })
    } else dialog.showSaveDialog = async () => ({ canceled: false, filePath: options.target })
  }, { target, native: nativeDialog })
  await page.locator('.transfer-row').getByRole('button', { name: '保存', exact: true }).click()
  if (nativeDialog) {
    const ownerHandle = await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find(w => w.isVisible())
      return window.getNativeWindowHandle().readBigUInt64LE().toString()
    })
    execFileSync('powershell.exe', ['-NoProfile', '-File', resolve(repository, 'scripts/dev/confirm_owned_save_dialog.ps1'), '-MainWindowHandle', ownerHandle, '-ExpectedFileName', '中文设备配置.cfg'], { env, windowsHide: true, timeout: 20000 })
    evidence.nativeDialog = 'PASS: owned Windows Save As invoked through UI Automation; filename verified'
  }
  await page.locator('.sftp-panel:visible .transfer-queue').getByRole('button', { name: '历史', exact: true }).click()
  await page.locator('.transfer-row').filter({ hasText: '已完成' }).waitFor()
  const globalSftp = await page.locator('.task-progress-hint').count()
  const content = await readFile(target)
  if (content.toString() !== 'isolated device configuration\n') throw new Error('local file content differs')
  evidence.tests.push({ save: 'PASS', size: content.length, sha256: createHash('sha256').update(content).digest('hex') })
  const terminalBefore = await page.locator('.xterm-screen').count()
  await page.getByRole('button', { name: 'SFTP', exact: true }).click()
  await page.getByRole('button', { name: 'SFTP', exact: true }).click()
  if (await page.locator('.xterm-screen').count() !== terminalBefore) throw new Error('terminal remounted')
  await page.locator('.sftp-files tr').filter({ hasText: 'startup.cfg' }).waitFor()
  evidence.tests.push('panel hide/show preserves terminal and SFTP session')
  // Prepare real single, multiple and directory files through Main. OS drop
  // target commit is reported separately, never inferred from this handoff.
  const sftpPanel = page.locator('.sftp-panel:visible')
  const rows = sftpPanel.locator('.sftp-files tr')
  await rows.filter({ hasText: 'startup.cfg' }).locator('input[type=checkbox]').check()
  await sftpPanel.getByRole('button', { name: '准备拖出', exact: true }).click()
  await sftpPanel.getByRole('button', { name: '拖到桌面 / 文件夹', exact: true }).waitFor()
  await rows.filter({ hasText: '日志目录' }).locator('input[type=checkbox]').check()
  await sftpPanel.getByRole('button', { name: '准备拖出', exact: true }).click()
  await sftpPanel.getByRole('button', { name: '拖到桌面 / 文件夹', exact: true }).waitFor()
  const stagedDrag = await (async () => {
    const root = resolve(runRoot, 'data/runtime/temp/sftp-drag')
    const result = []
    for (const folder of await readdir(root)) for (const index of await readdir(resolve(root, folder))) for (const name of await readdir(resolve(root, folder, index))) {
      const data = await readFile(resolve(root, folder, index, name))
      result.push({ name, size: data.length, sha256: createHash('sha256').update(data).digest('hex') })
    }
    return result
  })()
  if (!stagedDrag.some(item => item.name === '日志目录.zip') || stagedDrag.filter(item => item.name === 'startup.cfg').length < 2) throw new Error('native drag staging incomplete')
  evidence.nativeDragPreparation = stagedDrag
  evidence.nativeDragDropTarget = 'NOT VERIFIED: staging verified; no claim that Windows Explorer committed a drop'
  await rows.filter({ hasText: '日志目录' }).locator('input[type=checkbox]').uncheck()
  evidence.tests.push({ globalSftpHintCount: globalSftp })
  const deviceRow = page.locator('.device-row').filter({ hasText: 'LAB-SFTP-SW' })
  await deviceRow.dblclick()
  await deviceRow.dblclick()
  await page.waitForFunction(() => document.querySelectorAll('.terminal-tab').length === 3)
  const ids = await page.locator('.terminal-pane').evaluateAll(items => items.map(item => item.getAttribute('data-session-id')))
  if (new Set(ids).size !== 3) throw new Error('duplicate Session ID')
  for (const [index, id] of ids.entries()) {
    const tab = page.locator('.terminal-tab').nth(index)
    await tab.click()
    const input = page.locator(`[data-session-id="${id}"] .xterm-helper-textarea`)
    await input.focus()
    await page.keyboard.type(`display unique-${index}`)
    await page.keyboard.press('Enter')
    await page.waitForFunction(({ id, index }) => document.querySelector(`[data-session-id="${id}"] .xterm-screen`)?.textContent?.includes(`fixture interactive response: display unique-${index}`), { id, index })
  }
  await page.locator('.terminal-tab').nth(2).click()
  await page.locator('.xterm-helper-textarea').last().focus()
  await page.keyboard.type('display watch')
  await page.keyboard.press('Enter')
  await page.locator('.terminal-tab').nth(0).click()
  await page.locator(`[data-session-id="${ids[0]}"] .xterm-helper-textarea`).focus()
  await page.keyboard.type('pending-unsent')
  await page.waitForTimeout(200)
  await page.locator('.terminal-tab').nth(2).click()
  const inspectPanes = () => page.locator('.terminal-pane').evaluateAll(items => items.map(item => ({ id: item.getAttribute('data-session-id'), state: item.__vueParentComponent.exposed.inspect() })))
  const before = await inspectPanes()
  await page.evaluate(() => { window.__ncTerminalNodes = [...document.querySelectorAll('.terminal-pane')] })
  const memoryBefore = await app.evaluate(({ app }) => app.getAppMetrics().filter(item => item.type === 'Tab').map(item => ({ pid: item.pid, memory: item.memory })))
  const connectionsBefore = JSON.parse(await readFile(evidence.fixture.metrics_path, 'utf8'))
  const routePaths = ['/network/devices', '/ac-management/fit-aps', '/tasks', '/config-center', '/tools']
  for (let index = 0; index < 20; index++) {
    await page.evaluate(async path => {
      const root = document.querySelector('#app').__vue_app__
      await root.config.globalProperties.$router.push(path)
    }, routePaths[index % routePaths.length])
  }
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/console') })
  await page.locator('.terminal-tab').nth(2).waitFor()
  const after = await inspectPanes()
  const nodesSame = await page.evaluate(() => window.__ncTerminalNodes.every((node, index) => node === document.querySelectorAll('.terminal-pane')[index]))
  if (!nodesSame || ids.join() !== after.map(item => item.id).join()) throw new Error('terminal instance lost across routes')
  await page.waitForFunction(() => document.querySelectorAll('.terminal-pane')[2]?.textContent?.includes('background-tick-19'))
  evidence.crossPage = { switches: 20, before, after, nodesSame, memoryBefore, memoryAfter: await app.evaluate(({ app }) => app.getAppMetrics().filter(item => item.type === 'Tab').map(item => ({ pid: item.pid, memory: item.memory }))) }
  evidence.crossPage.connectionsBefore = connectionsBefore
  evidence.crossPage.connectionsAfter = JSON.parse(await readFile(evidence.fixture.metrics_path, 'utf8'))
  if (evidence.crossPage.connectionsAfter.connections.length !== connectionsBefore.connections.length || evidence.crossPage.connectionsAfter.shells !== connectionsBefore.shells) throw new Error('page switch reconnected a transport')
  evidence.crossPage.warmMemory = []
  const cdp = await page.context().newCDPSession(page)
  for (let round = 0; round < 3; round++) {
    for (let index = 0; index < 20; index++) await page.evaluate(async path => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(path) }, routePaths[index % routePaths.length])
    await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/console') })
    await cdp.send('HeapProfiler.collectGarbage')
    evidence.crossPage.warmMemory.push(await cdp.send('Runtime.getHeapUsage'))
  }
  await cdp.detach()
  evidence.crossPage.switches = 80
  evidence.crossPage.nodesSameAfter80 = await page.evaluate(() => window.__ncTerminalNodes.every((node, index) => node === document.querySelectorAll('.terminal-pane')[index]))
  for (let index = 0; index < 3; index++) {
    const needle = `fixture interactive response: display unique-${index}`
    const count = pane => pane.state.lines.filter(line => line.includes(needle)).length
    if (count(before[index]) !== 1 || count(after[index]) !== 1) throw new Error('repeated or missing output across pages')
  }
  if (!after[0].state.lines.join('\n').includes('pending-unsent')) throw new Error('unsent input lost')
  if (before[0].state.cursorX !== after[0].state.cursorX) throw new Error('cursor changed across routes')
  evidence.sessionIds = ids
  // Exercise actual UI -> Python dispatcher -> independent interactive shells.
  await page.locator('.quick-buttons').getByRole('button', { name: '版本', exact: true }).click()
  await page.waitForFunction(() => [...document.querySelectorAll('.el-message')].some(item => item.textContent.includes('命令已写入')))
  await page.getByRole('button', { name: '终端会话', exact: true }).click()
  const sessionRows = page.locator('.session-row')
  await sessionRows.filter({ hasText: 'LAB-SFTP-SW-01' }).locator('input[type=checkbox]').check()
  await sessionRows.filter({ hasText: 'LAB-SFTP-SW-02' }).locator('input[type=checkbox]').check()
  await page.getByLabel('发送目标', { exact: true }).selectOption('selected')
  await page.getByLabel('批量命令', { exact: true }).fill('display batch-one\n\ndisplay batch-two')
  await page.getByRole('button', { name: '预览发送', exact: true }).click()
  await page.getByRole('button', { name: '确认发送', exact: true }).click()
  await page.waitForFunction(() => [...document.querySelectorAll('.terminal-pane')].filter(pane => pane.__vueParentComponent.exposed.inspect().lines.some(line => line.includes('fixture interactive response: display batch-two'))).length === 2)
  evidence.batch = { targetSessionIds: ids.slice(0, 2), outputVerified: true }
  if (await page.getByRole('button', { name: '发送详情', exact: true }).count()) throw new Error('removed send details entry remains')
  if (await page.getByRole('dialog', { name: '命令发送详情', exact: true }).count()) throw new Error('removed send details dialog remains')
  const thirdLog = await api(`history/${ids[2]}/transcript`)
  if (thirdLog.text.includes('batch-one')) throw new Error('unselected third session received batch command')
  await page.getByLabel('发送目标', { exact: true }).selectOption('new')
  await page.getByLabel('批量命令', { exact: true }).fill('display new-tab')
  await page.getByRole('button', { name: '预览发送', exact: true }).click()
  await page.getByRole('button', { name: '确认发送', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.terminal-tab').length === 4)
  await page.waitForFunction(() => document.querySelectorAll('.terminal-pane')[3]?.textContent.includes('fixture interactive response: display new-tab'))
  const newId = await page.locator('.terminal-pane').nth(3).getAttribute('data-session-id')
  evidence.newTab = { id: newId, originals: ids }
  evidence.sessionIds.push(newId)
  await page.getByLabel('发送目标', { exact: true }).selectOption('window')
  await page.getByLabel('批量命令', { exact: true }).fill('display detached')
  await page.getByRole('button', { name: '预览发送', exact: true }).click()
  const detachedPromise = app.waitForEvent('window')
  await page.getByRole('button', { name: '确认发送', exact: true }).click()
  const detached = await detachedPromise
  await detached.waitForFunction(() => document.querySelector('.xterm-screen')?.textContent?.includes('fixture interactive response: display detached'), { timeout: 45000 })
  const detachedId = await detached.locator('.terminal-pane').getAttribute('data-session-id')
  if (evidence.sessionIds.includes(detachedId)) throw new Error('detached window reused existing shell')
  await detached.screenshot({ path: resolve(output, 'detached-terminal.png') })
  evidence.detachedWindow = { sessionId: detachedId, parentSessionId: newId }
  await detached.close()
  for (let attempt = 0; attempt < 40; attempt++) {
    const value = await api(`history/${detachedId}`)
    if (value.state === 'CLOSED' && value.recording_status === 'COMPLETED') { evidence.detachedWindow.closed = value; break }
    await new Promise(done => setTimeout(done, 100))
  }
  if (!(await api('sessions')).items.some(item => item.session_id === newId && item.state === 'RUNNING')) throw new Error('closing detached affected parent')
  evidence.tests.push('quick button, two selected sessions, new independent tag, detached window and independent close')
  await page.locator('.terminal-tab').nth(0).click()
  await page.getByRole('button', { name: '分屏', exact: true }).click()
  await page.getByText('左右分屏', { exact: true }).click()
  const divider = await page.getByRole('button', { name: '调整分屏大小', exact: true }).boundingBox()
  await page.mouse.move(divider.x + divider.width / 2, divider.y + 80)
  await page.mouse.down()
  await page.mouse.move(divider.x + 70, divider.y + 80)
  await page.mouse.up()
  const gridBefore = await page.locator('.terminal-grid').getAttribute('style')
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/network/devices') })
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/console') })
  if (gridBefore !== await page.locator('.terminal-grid').getAttribute('style')) throw new Error('split ratio lost')
  evidence.crossPage.splitStyle = gridBefore
  const sftpListingBefore = await page.locator('.sftp-panel:visible .sftp-files').innerText()
  const connectedSftp = (await api('sftp/sessions')).items.find(item => item.workspace_id === ids[0])
  const backgroundDownload = await api(`sftp/sessions/${connectedSftp.session_id}/download`, { path: '/large.bin' })
  const downloadBefore = (await api('sftp/transfers')).items.find(item => item.task_id === backgroundDownload.task_id)
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/network/devices') })
  let downloadAfter
  for (let attempt = 0; attempt < 150; attempt++) {
    downloadAfter = (await api('sftp/transfers')).items.find(item => item.task_id === backgroundDownload.task_id)
    if (downloadAfter.status === 'READY') break
    if (downloadAfter.status === 'FAILED') throw new Error('background SFTP download failed')
    await new Promise(done => setTimeout(done, 150))
  }
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/console') })
  if (downloadAfter.status !== 'READY') throw new Error('background SFTP download did not finish')
  if (sftpListingBefore !== await page.locator('.sftp-panel:visible .sftp-files').innerText()) throw new Error('SFTP listing lost across pages')
  evidence.crossPage.sftp = { before: downloadBefore, after: downloadAfter, listingPreserved: true }
  await page.getByRole('button', { name: '展开或收起左侧列表', exact: true }).click()
  const hint = page.getByRole('button', { name: '关闭任务进度提示' })
  if (await hint.isVisible()) await hint.click()
  evidence.displays = await app.evaluate(({ screen }) => screen.getAllDisplays().map(d => ({ bounds: d.bounds, workArea: d.workArea, scaleFactor: d.scaleFactor, size: d.size })))
  for (const [width, height] of [[1920, 1080], [2560, 1440]]) {
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find(w => w.isVisible())
      window.setFullScreen(false)
      window.unmaximize()
    })
    await page.waitForTimeout(300)
    const bounds = await app.evaluate(({ BrowserWindow }, dimensions) => {
      const window = BrowserWindow.getAllWindows().find(w => w.isVisible())
      window.setBounds({ x: 0, y: 0, width: dimensions.width, height: dimensions.height })
      return window.getBounds()
    }, { width, height })
    await page.waitForTimeout(500)
    await page.screenshot({ path: resolve(output, `electron-window-${width}x${height}.png`) })
    const physical = evidence.displays.some(d => d.size.width * d.scaleFactor === width && d.size.height * d.scaleFactor === height)
    evidence.resolutions.push({ requested: { width, height }, actualBounds: bounds, physicalDisplayMatches: physical, status: physical ? 'PASS: actual Electron on matching display' : 'PARTIAL: actual Electron window only; physical display does not match' })
  }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  process.stdout.write(JSON.stringify({ runRoot, sessionIds: ids, crossPage: { switches: 20, nodesSame }, tests: evidence.tests, resolutions: evidence.resolutions }) + '\n')
} catch (error) {
  if (page && !page.isClosed()) {
    await page.screenshot({ path: resolve(output, 'acceptance-failure.png') }).catch(() => undefined)
    process.stderr.write((await page.locator('body').innerText().catch(() => '')).slice(-2000) + '\n')
  }
  evidence.failure = String(error)
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  throw error
} finally {
  if (evidence.sessionIds) {
    evidence.recordings = []
    for (const id of evidence.sessionIds) await api(`sessions/${id}`, undefined, 'DELETE').catch(() => undefined)
    for (const id of evidence.sessionIds) {
      for (let attempt = 0; attempt < 50; attempt++) {
        const item = await api(`history/${id}`).catch(() => null)
        if (item && ['COMPLETED', 'FAILED', 'INCOMPLETE'].includes(item.recording_status)) { evidence.recordings.push(item); break }
        await new Promise(done => setTimeout(done, 100))
      }
    }
    await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  }
  await app?.close()
  vite?.kill()
  fixture?.stdin.end('\n')
  // Preserve this run's small evidence and saved file; no recursive deletion.
}
