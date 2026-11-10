import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const { chromium } = createRequire(path.join(process.cwd(), 'package.json'))('@playwright/test')

const port = Number(process.argv[2])
const outputDir = path.resolve(process.argv[3])
if (!Number.isInteger(port) || port <= 0 || !process.argv[3]) {
  throw new Error('usage: node ground_unattended_r2_3_2_gui_capture.mjs <cdp-port> <output-dir>')
}

await fs.mkdir(outputDir, { recursive: true })
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
const pages = browser.contexts().flatMap((context) => context.pages())
const page = pages.find((candidate) => !candidate.url().startsWith('devtools:')) || pages[0]
if (!page) throw new Error('no Electron renderer page')

const evidence = {
  cdp_port: port,
  captured_at: new Date().toISOString(),
  page: { url: page.url(), title: await page.title() },
  screenshots: [],
  interactions: [],
}

async function capture(name) {
  const file = path.join(outputDir, `${name}.png`)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  evidence.screenshots.push({ name, file, url: page.url() })
}

async function openTab(label, name) {
  const tab = page.getByRole('tab', { name: label, exact: true })
  await tab.click({ timeout: 15_000 })
  await page.waitForTimeout(1200)
  evidence.interactions.push({ action: 'open_tab', label, ok: true, url: page.url() })
  await capture(name)
}

try {
  await page.waitForLoadState('domcontentloaded', { timeout: 15_000 }).catch(() => {})
  await page.waitForTimeout(1500)
  await capture('01-overview-before')
  await openTab('心跳检测', '02-heartbeat')
  await openTab('Syslog 日志', '03-syslog')
  const beforeMrFilter = page.getByPlaceholder('MR 设备名称')
  if (await beforeMrFilter.count()) {
    await beforeMrFilter.fill('列车001-MR-CT')
    await page.getByRole('button', { name: '查询', exact: true }).click({ timeout: 15_000 })
    await page.waitForTimeout(1_500)
    evidence.interactions.push({ action: 'filter_initial_mr', ok: true, value: '列车001-MR-CT', url: page.url() })
    await capture('03-syslog-mr001-before')
  } else {
    evidence.interactions.push({ action: 'filter_initial_mr', ok: false, error: 'MR 设备名称 filter not found' })
  }
  await openTab('AC-Mesh-Link', '04-ac-reconcile')
  await page.waitForTimeout(12_000)
  await openTab('Syslog 日志', '05-syslog-after-switch')
  const mrFilter = page.getByPlaceholder('MR 设备名称')
  if (await mrFilter.count()) {
    await mrFilter.fill('列车001-MR-CT')
    await page.getByRole('button', { name: '查询', exact: true }).click({ timeout: 15_000 })
    await page.waitForTimeout(1_500)
    evidence.interactions.push({ action: 'filter_switched_mr', ok: true, value: '列车001-MR-CT', url: page.url() })
    await capture('05-syslog-mr001-after')
  } else {
    evidence.interactions.push({ action: 'filter_switched_mr', ok: false, error: 'MR 设备名称 filter not found' })
  }
  await openTab('运行概览', '05-overview-after')
  const stopButton = page.getByRole('button', { name: '正常停止', exact: true })
  if (await stopButton.count() && await stopButton.isEnabled()) {
    await stopButton.click({ timeout: 15_000 })
    const confirmation = page.getByRole('dialog', { name: '确认正常停止' })
    if (await confirmation.count()) {
      await confirmation.getByRole('button', { name: '正常停止', exact: true }).click({ timeout: 15_000 })
    }
    await page.waitForTimeout(4_000)
    evidence.interactions.push({ action: 'stop_ground', ok: true, label: '正常停止', url: page.url() })
    await capture('06-ground-stopped-heartbeat-resident')
    await openTab('心跳检测', '07-heartbeat-after-ground-stop')
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 20_000 })
    await page.waitForTimeout(2_000)
    evidence.interactions.push({ action: 'renderer_reload', ok: true, url: page.url() })
    await capture('08-renderer-reload')
  } else {
    evidence.interactions.push({ action: 'stop_ground', ok: false, error: 'button not found' })
  }
  evidence.page_after = { url: page.url(), title: await page.title() }
} catch (error) {
  evidence.error = String(error)
  evidence.interactions.push({ action: 'capture_sequence', ok: false, error: String(error) })
}

await fs.writeFile(path.join(outputDir, 'evidence.json'), JSON.stringify(evidence, null, 2), 'utf8')
console.log(JSON.stringify(evidence))
await browser.close()
