import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const { chromium } = createRequire(path.join(process.cwd(), 'package.json'))('@playwright/test')

const port = Number(process.argv[2])
const outputDir = path.resolve(process.argv[3] || '')
const waitSeconds = Number(process.argv[4] || 65)
if (!Number.isInteger(port) || port <= 0 || !process.argv[3] || !Number.isFinite(waitSeconds) || waitSeconds < 1) {
  throw new Error('usage: node ground_unattended_r2_3_3_gui_latency_capture.mjs <cdp-port> <output-dir> [wait-seconds]')
}

await fs.mkdir(outputDir, { recursive: true })
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
const pages = browser.contexts().flatMap((context) => context.pages())
const page = pages.find((candidate) => !candidate.url().startsWith('devtools:')) || pages[0]
if (!page) throw new Error('no Electron renderer page')

const evidence = {
  cdp_port: port,
  wait_seconds: waitSeconds,
  captured_at: new Date().toISOString(),
  page: { url: page.url(), title: await page.title() },
  captures: [],
  interactions: [],
}

async function capture(name) {
  const file = path.join(outputDir, `${name}.png`)
  const bodyText = await page.locator('body').innerText().catch(() => '')
  await page.screenshot({ path: file, fullPage: false, animations: 'disabled', timeout: 10_000 })
  evidence.captures.push({
    name,
    file,
    captured_at: new Date().toISOString(),
    url: page.url(),
    text_markers: bodyText.split('\n').filter((line) => /当前 AP|上一个 AP|最后切换|最后日志|位置 API|Renderer|Paint/i.test(line)).slice(0, 30),
  })
}

async function openFilteredSyslog(stage) {
  const tab = page.getByRole('tab', { name: 'Syslog 日志', exact: true })
  await tab.click({ timeout: 15_000 })
  await page.waitForTimeout(1_200)
  const filter = page.getByPlaceholder('MR 设备名称')
  if (!(await filter.count())) throw new Error('MR 设备名称 filter not found')
  await filter.fill('列车001-MR-CT')
  await page.getByRole('button', { name: '查询', exact: true }).click({ timeout: 15_000 })
  await page.waitForTimeout(1_500)
  evidence.interactions.push({ action: 'filter_syslog', stage, ok: true, value: '列车001-MR-CT', url: page.url() })
}

await page.waitForLoadState('domcontentloaded', { timeout: 15_000 }).catch(() => {})
await page.waitForTimeout(1_500)
await openFilteredSyslog('before_switch')
await capture('syslog-mr001-ap-a-before')

await page.waitForTimeout(waitSeconds * 1_000)
await openFilteredSyslog('after_switch')
await capture('syslog-mr001-ap-b-after')

evidence.page_after = { url: page.url(), title: await page.title() }
await fs.writeFile(path.join(outputDir, 'evidence.json'), JSON.stringify(evidence, null, 2), 'utf8')
console.log(JSON.stringify(evidence))
await browser.close()
