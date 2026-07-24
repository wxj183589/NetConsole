import { expect, test } from '@playwright/test'

test('表头、内容对齐和横向滚动在标准窗口与缩放下稳定', async ({ page }, testInfo) => {
  await page.goto('/tests/visual/', { waitUntil: 'networkidle' })
  const table = page.locator('.nc-data-table').first()
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

test('MESH 归属区间保持 190px 且不被固定列遮挡', async ({ page }, testInfo) => {
  await page.goto('/tests/visual/', { waitUntil: 'networkidle' })
  const fixture = page.locator('[data-mesh-link-table]')
  await expect(fixture).toBeVisible()
  const sectionHeader = fixture.locator('th.el-table__cell').filter({ hasText: '归属区间' }).first()
  const peerRadioHeader = fixture.locator('th.el-table__cell').filter({ hasText: 'PEER Radio' }).first()
  await expect(sectionHeader).toBeVisible()

  const facts = await fixture.evaluate((element) => {
    const headers = [...element.querySelectorAll<HTMLElement>('.el-table__header th.el-table__cell')]
    const section = headers.find((header) => header.textContent?.trim() === '归属区间')
    const peerRadio = headers.find((header) => header.textContent?.trim() === 'PEER Radio')
    const bodyWrap = element.querySelector<HTMLElement>('.el-scrollbar__wrap')
    const fixedHeaders = headers.filter((header) => getComputedStyle(header).position === 'sticky')
    const sectionRect = section?.getBoundingClientRect()
    const peerRadioRect = peerRadio?.getBoundingClientRect()
    return {
      fixedHeaderCount: fixedHeaders.length,
      horizontalOverflow: Boolean(bodyWrap && bodyWrap.scrollWidth > bodyWrap.clientWidth),
      sectionWidth: sectionRect?.width ?? 0,
      sectionEndsBeforePeerRadio: Boolean(sectionRect && peerRadioRect && sectionRect.right <= peerRadioRect.left + 1),
    }
  })

  expect(facts.sectionWidth).toBeGreaterThanOrEqual(188)
  expect(facts.sectionEndsBeforePeerRadio).toBe(true)
  expect(facts.fixedHeaderCount).toBe(1)
  expect(facts.horizontalOverflow).toBe(true)
  await expect(peerRadioHeader).toBeVisible()

  const screenshot = await fixture.screenshot({ path: testInfo.outputPath('mesh-link-section.png') })
  expect(screenshot.byteLength).toBeGreaterThan(1_000)
})
