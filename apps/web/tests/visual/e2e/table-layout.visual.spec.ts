import { expect, test } from '@playwright/test'

test('表头、内容对齐和横向滚动在标准窗口与缩放下稳定', async ({ page }, testInfo) => {
  await page.goto('/tests/visual/', { waitUntil: 'networkidle' })
  const table = page.locator('.nc-data-table')
  await expect(table).toBeVisible()

  const facts = await table.evaluate((element) => {
    const headers = [...element.querySelectorAll<HTMLElement>('.el-table__header th.el-table__cell')]
    const cells = [...element.querySelectorAll<HTMLElement>('.el-table__body td.el-table__cell')]
    const scroll = element.querySelector<HTMLElement>('.nc-data-table__scroll')
    return {
      headerWidths: headers.map((header) => ({ client: header.clientWidth, scroll: header.scrollWidth })),
      centeredCells: cells.filter((cell) => !cell.querySelector('.nc-table-cell--left')).every((cell) => getComputedStyle(cell).textAlign === 'center'),
      horizontalOverflow: Boolean(scroll && scroll.scrollWidth >= scroll.clientWidth),
    }
  })

  expect(facts.headerWidths.length).toBe(6)
  expect(facts.headerWidths.every(({ client, scroll }) => client + 2 >= scroll)).toBe(true)
  expect(facts.centeredCells).toBe(true)
  expect(facts.horizontalOverflow).toBe(true)

  const screenshot = await page.screenshot({ path: testInfo.outputPath('table-layout.png'), fullPage: true })
  expect(screenshot.byteLength).toBeGreaterThan(1_000)
})
