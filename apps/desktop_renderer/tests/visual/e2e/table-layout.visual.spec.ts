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

async function openBottomRightContextMenu(page: import('@playwright/test').Page) {
  const fixture = page.locator('[data-context-menu-table]')
  const bodyWrap = fixture.locator('.el-scrollbar__wrap').first()
  await bodyWrap.evaluate((element) => { element.scrollTop = element.scrollHeight })
  const lastCell = fixture.locator('.el-table__body tr').last().locator('td.el-table__cell').last()
  await lastCell.scrollIntoViewIfNeeded()
  await fixture.evaluate((element) => {
    const bottom = element.getBoundingClientRect().bottom
    window.scrollBy(0, bottom - window.innerHeight + 4)
  })
  const cellBox = await lastCell.boundingBox()
  expect(cellBox).not.toBeNull()
  const anchor = {
    x: cellBox!.x + cellBox!.width / 2,
    y: cellBox!.y + cellBox!.height / 2,
  }
  await page.mouse.click(anchor.x, anchor.y, { button: 'right' })
  const menu = page.locator('body > .nc-data-table__context-menu')
  await expect(menu).toBeVisible()
  return { fixture, bodyWrap, menu, anchor }
}

test('右下角菜单挂载到 body、向左上翻转并在滚动和缩放时关闭', async ({ page }) => {
  await page.goto('/tests/visual/', { waitUntil: 'networkidle' })
  const { fixture, bodyWrap, menu, anchor } = await openBottomRightContextMenu(page)
  const viewport = page.viewportSize()!
  const facts = await menu.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const table = document.querySelector<HTMLElement>('[data-context-menu-table] .nc-data-table')
    const header = document.querySelector<HTMLElement>('[data-context-menu-table] th.el-table__cell')
    return {
      directBodyChild: element.parentElement === document.body,
      rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
      tableOverflow: table ? getComputedStyle(table).overflow : '',
      menuZIndex: Number.parseInt(getComputedStyle(element).zIndex || '0', 10),
      headerZIndex: Number.parseInt(header ? getComputedStyle(header).zIndex || '0' : '0', 10),
    }
  })

  expect(facts.directBodyChild).toBe(true)
  expect(facts.tableOverflow).toBe('hidden')
  expect(facts.rect.left).toBeGreaterThanOrEqual(7.5)
  expect(facts.rect.top).toBeGreaterThanOrEqual(7.5)
  expect(facts.rect.right).toBeLessThanOrEqual(viewport.width - 7.5)
  expect(facts.rect.bottom).toBeLessThanOrEqual(viewport.height - 7.5)
  expect(facts.rect.left).toBeLessThan(anchor.x)
  expect(facts.rect.top).toBeLessThan(anchor.y)
  expect(facts.menuZIndex).toBeGreaterThan(facts.headerZIndex)

  await bodyWrap.evaluate((element) => element.dispatchEvent(new Event('scroll')))
  await expect(menu).toBeHidden()

  const reopened = await openBottomRightContextMenu(page)
  await page.setViewportSize({ width: viewport.width - 1, height: viewport.height - 1 })
  await expect(reopened.menu).toBeHidden()
  await expect(fixture).toBeVisible()
})

test('短窗口菜单内部滚动且末尾删除动作可访问', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 260 })
  await page.goto('/tests/visual/', { waitUntil: 'networkidle' })
  const { menu } = await openBottomRightContextMenu(page)
  const facts = await menu.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    return {
      rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowY: style.overflowY,
      overscrollBehavior: style.overscrollBehavior,
    }
  })
  expect(facts.rect.left).toBeGreaterThanOrEqual(7.5)
  expect(facts.rect.top).toBeGreaterThanOrEqual(7.5)
  expect(facts.rect.right).toBeLessThanOrEqual(412.5)
  expect(facts.rect.bottom).toBeLessThanOrEqual(252.5)
  expect(facts.scrollHeight).toBeGreaterThan(facts.clientHeight)
  expect(facts.overflowY).toBe('auto')
  expect(facts.overscrollBehavior).toBe('contain')

  await menu.evaluate((element) => {
    element.scrollTop = element.scrollHeight
    element.dispatchEvent(new Event('scroll'))
  })
  await expect(menu).toBeVisible()
  const deleteAction = menu.getByRole('menuitem', { name: '删除' })
  await deleteAction.scrollIntoViewIfNeeded()
  await expect(deleteAction).toBeVisible()
  await deleteAction.click()
  await expect(page.locator('[data-last-context-action]')).toHaveText('delete')
  await expect(menu).toBeHidden()
})
