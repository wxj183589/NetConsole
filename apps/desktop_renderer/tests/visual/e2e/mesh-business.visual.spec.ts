import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const benchmarkPath = path.resolve('../../.local-reports/mesh-business-benchmark.json')
const benchmark = fs.existsSync(benchmarkPath) ? JSON.parse(fs.readFileSync(benchmarkPath, 'utf8')) : null
const summary = { ap_total: 128, grades: { GOOD: 110, WARNING: 9, BAD: 4, INSUFFICIENT: 5, UNRECOGNIZED: 2 }, single_link_count: 3, single_link_seconds: 18, single_link_ap_count: 2, single_link_radios: [1, 2], good_threshold: 30, warning_threshold: 25, backup_available_threshold: 30, minimum_samples: 10 }

for (const records of [50_000, 200_000, 500_000, 1_000_000]) {
  for (const variant of ['before', 'after']) {
    test(`Mesh ${records} ${variant}: real chart paint and lazy AP details`, async ({ page }, info) => {
      test.setTimeout(90_000)
      const payloadFile = benchmark && path.join(benchmark.root, String(records), `chart-${variant}.json`)
      test.skip(!payloadFile || !fs.existsSync(payloadFile), 'Run benchmark_mesh_business with --keep-chart-payloads first')
      const errors: string[] = []
      const details: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      await page.route('**/mesh-benchmark.json', route => route.fulfill({ path: payloadFile, contentType: 'application/json' }))
      await page.route(url => url.pathname.startsWith('/api/'), async route => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith('/business-summary')) { await route.fulfill({ json: summary }); return }
        if (url.pathname.endsWith('/ap-signal-statistics')) {
          details.push(url.search)
          await route.fulfill({ json: { items: [{ peer_ap_name: '合成 AP 001', peer_ap_mac: '0011-2233-4400', station: '合成站', section: '合成区间', avg_rssi: 31, min_rssi: 24, max_rssi: 42, p10_rssi: 28, valid_sample_count: 80, weak_sample_count: 10, weak_ratio: .125, signal_grade: 'WARNING' }], total: 80, page: Number(url.searchParams.get('page') || 1), page_size: 50 } })
          return
        }
        if (url.pathname.includes('/table-preferences')) { await route.fulfill({ json: {} }); return }
        await route.fulfill({ json: { items: [] } })
      })
      await page.goto('/tests/visual/mesh-business.html?netconsole_host=electron')
      await expect(page.locator('[data-render-ms]')).toBeVisible({ timeout: 75_000 })
      await expect(page.locator('canvas')).toHaveCount(1)
      await expect(page.locator('.business-card')).toHaveCount(7)
      expect(await page.locator('body').evaluate(el => getComputedStyle(el).color)).toBe('rgb(242, 244, 247)')
      expect(details).toHaveLength(0)
      const renderMs = Number(await page.locator('[data-render-ms]').getAttribute('data-value'))
      await info.attach('mesh-render-measurement', { body: JSON.stringify({ records, variant, renderMs, project: info.project.name }), contentType: 'application/json' })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if (records === 50_000 && variant === 'after') {
        await page.screenshot({ path: info.outputPath('mesh-summary.png'), fullPage: true })
        await page.locator('.business-card').first().click()
        await expect(page.getByRole('dialog')).toBeVisible()
        await expect(page.getByRole('dialog')).toContainText('合成 AP 001')
        await expect(page.locator('.el-overlay-dialog')).toHaveCSS('position', 'fixed')
        await page.getByRole('dialog').evaluate(async el => {
          await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished))
        })
        expect(details[0]).toContain('signal_grade=RECOGNIZED')
        await page.screenshot({ path: info.outputPath('mesh-ap-details.png'), fullPage: true })
      }
      expect(errors).toEqual([])
    })
  }
}
