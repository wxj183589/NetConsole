import { expect, test } from '@playwright/test'
import path from 'node:path'

const chartPayload = path.resolve(
  '../../../test-data/NetConsole/mesh-business-5a2c32e42f7f42f08d410ca71ac94419/50000/chart-after.json',
)
const summary = {
  ap_total: 128,
  grades: { GOOD: 110, WARNING: 9, BAD: 4, INSUFFICIENT: 5, UNRECOGNIZED: 2 },
  single_link_count: 3,
  single_link_seconds: 18,
  single_link_ap_count: 2,
  single_link_radios: [1, 2],
  good_threshold: 30,
  warning_threshold: 25,
  backup_available_threshold: 30,
  minimum_samples: 10,
}

test('Mesh Phase 9 scope controls and chart remain readable at target viewports', async ({ page }, info) => {
  test.setTimeout(90_000)
  const summaryRequests: string[] = []
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.route('**/mesh-benchmark.json', route => route.fulfill({ path: chartPayload, contentType: 'application/json' }))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/business-summary')) {
      summaryRequests.push(url.search)
      await route.fulfill({ json: summary })
      return
    }
    await route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
  })
  await page.goto('/tests/visual/mesh-business.html?netconsole_host=electron')
  await expect(page.locator('canvas')).toHaveCount(1)
  await expect(page.locator('.business-card')).toHaveCount(7)
  await expect(page.getByText('排除车辆段', { exact: false })).toBeVisible()
  await expect(page.getByText('排除停车场', { exact: false })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('mesh-phase9.png'), fullPage: true })

  await page.locator('.business-scope .el-checkbox').first().click()
  await expect.poll(() => summaryRequests.length).toBeGreaterThan(1)
  expect(summaryRequests.at(-1)).toContain('exclude_depot=false')
  expect(summaryRequests.at(-1)).toContain('exclude_parking=true')
  expect(consoleErrors).toEqual([])
})
