import { expect, test, type Page } from '@playwright/test'

type MatrixVariant = {
  locale: 'en' | 'zh-CN'
  theme: 'light' | 'dark'
}

function variantForProject(projectName: string): MatrixVariant {
  return {
    locale: projectName.includes('-en-') ? 'en' : 'zh-CN',
    theme: projectName.endsWith('-dark') ? 'dark' : 'light',
  }
}

async function openMatrix(page: Page, projectName: string): Promise<MatrixVariant> {
  const variant = variantForProject(projectName)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`/tests/visual/visual-matrix.html?locale=${variant.locale === 'en' ? 'en' : 'zh'}&theme=${variant.theme}`, {
    waitUntil: 'networkidle',
  })
  await expect(page.locator('[data-visual-matrix-root]')).toBeVisible()
  return variant
}

async function expectAppliedTheme(page: Page, theme: MatrixVariant['theme']): Promise<void> {
  const root = page.locator('html')
  await expect(root).toHaveAttribute('data-theme', theme)
  if (theme === 'dark') {
    await expect(root).toHaveClass(/(?:^|\s)dark(?:\s|$)/)
  } else {
    await expect(root).not.toHaveClass(/(?:^|\s)dark(?:\s|$)/)
  }
  const pageBackground = await root.evaluate((element) => getComputedStyle(element).getPropertyValue('--nc-bg-page').trim())
  expect(pageBackground).not.toBe('')
}

test('核心页面、导航和国际化初始状态可见且无横向溢出', async ({ page }, testInfo) => {
  const variant = await openMatrix(page, testInfo.project.name)
  const root = page.locator('[data-visual-matrix-root]')
  const pageIds = ['dashboard', 'devices', 'device-detail', 'fit-ap', 'trackside', 'online-mr', 'job-center', 'traffic', 'agent', 'settings']

  await expect(root.locator('[data-visual-sidebar]')).toBeVisible()
  await expect(root.locator('[data-visual-header]')).toBeVisible()
  await expect(root.locator('[data-visual-primary-action]')).toBeVisible()
  await expect(root.locator('[data-visual-secondary-action]')).toBeVisible()
  await expect(root.locator('[data-visual-page]')).toHaveCount(pageIds.length)
  for (const pageId of pageIds) {
    await expect(root.locator(`[data-visual-page="${pageId}"]`)).toBeVisible()
  }

  await expect(page.locator('html')).toHaveAttribute('data-visual-locale', variant.locale)
  await expect(page.locator('html')).toHaveAttribute('data-visual-theme', variant.theme)
  await expectAppliedTheme(page, variant.theme)

  const shell = root
  const sidebar = root.locator('[data-visual-sidebar]')
  const expandedSidebarWidth = await sidebar.evaluate((element) => element.getBoundingClientRect().width)
  await root.locator('[data-sidebar-toggle]').click()
  await expect(shell).toHaveClass(/visual-matrix-shell--collapsed/)
  const collapsedSidebarWidth = await sidebar.evaluate((element) => element.getBoundingClientRect().width)
  expect(collapsedSidebarWidth).toBeGreaterThan(0)
  expect(collapsedSidebarWidth).toBeLessThan(expandedSidebarWidth)
  await expect(root.locator('.visual-matrix-sidebar-title')).toBeHidden()
  const collapsedLayout = await root.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }))
  expect(collapsedLayout.scrollWidth).toBeLessThanOrEqual(collapsedLayout.clientWidth + 1)
  await root.locator('[data-sidebar-toggle]').click()
  await expect(shell).not.toHaveClass(/visual-matrix-shell--collapsed/)
  const layout = await root.evaluate((element) => ({
    rootScrollWidth: element.scrollWidth,
    rootClientWidth: element.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    viewportWidth: window.innerWidth,
  }))
  expect(layout.rootScrollWidth).toBeLessThanOrEqual(layout.rootClientWidth + 1)
  expect(layout.bodyScrollWidth).toBeLessThanOrEqual(layout.viewportWidth + 1)
})

test('NcDataTable、操作入口、上下文菜单和弹层保持可达', async ({ page }, testInfo) => {
  await openMatrix(page, testInfo.project.name)
  const table = page.locator('[data-visual-page="devices"] .nc-data-table')
  await expect(table).toBeVisible()

  const tableFacts = await table.evaluate((element) => {
    const headers = [...element.querySelectorAll<HTMLElement>('.el-table__header th.el-table__cell')]
    const bodyRows = element.querySelectorAll('.el-table__body tr')
    const actions = element.querySelectorAll('.el-table__body .el-button')
    const scroll = element.querySelector<HTMLElement>('.nc-data-table__scroll')
    return {
      headerCount: headers.length,
      headerWidths: headers.map((header) => ({ client: header.clientWidth, scroll: header.scrollWidth })),
      rowCount: bodyRows.length,
      actionCount: actions.length,
      scrollClientWidth: scroll?.clientWidth ?? 0,
      scrollWidth: scroll?.scrollWidth ?? 0,
    }
  })
  expect(tableFacts.headerCount).toBe(5)
  expect(tableFacts.headerWidths.every(({ client, scroll }) => client + 2 >= scroll)).toBe(true)
  expect(tableFacts.rowCount).toBe(3)
  expect(tableFacts.actionCount).toBeGreaterThan(0)
  expect(tableFacts.scrollWidth).toBeGreaterThanOrEqual(tableFacts.scrollClientWidth)

  await table.locator('.el-table__body tr').first().locator('td.el-table__cell').last().click({ button: 'right' })
  const menu = page.locator('body > .nc-data-table__context-menu')
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('menuitem')).toHaveCount(3)
  const menuBounds = await menu.boundingBox()
  const viewport = page.viewportSize()!
  expect(menuBounds).not.toBeNull()
  expect(menuBounds!.x).toBeGreaterThanOrEqual(0)
  expect(menuBounds!.y).toBeGreaterThanOrEqual(0)
  expect(menuBounds!.x + menuBounds!.width).toBeLessThanOrEqual(viewport.width)
  expect(menuBounds!.y + menuBounds!.height).toBeLessThanOrEqual(viewport.height)
  await menu.getByRole('menuitem').first().click()
  await expect(menu).toBeHidden()

  const jobCenter = page.locator('[data-visual-page="job-center"]')
  await jobCenter.locator('[data-visual-open-drawer]').click()
  const drawer = page.locator('[data-visual-drawer]')
  await expect(drawer).toBeVisible()
  await expect(drawer.locator('[data-visual-drawer-footer]')).toBeVisible()
  await page.waitForTimeout(350)
  const drawerBounds = await drawer.boundingBox()
  expect(drawerBounds).not.toBeNull()
  expect(drawerBounds!.x + drawerBounds!.width).toBeLessThanOrEqual(viewport.width)
  await drawer.locator('[data-visual-drawer-footer] button').first().click()
  await expect(drawer).toBeHidden()

  await jobCenter.locator('[data-visual-open-dialog]').click()
  const dialog = page.locator('[data-visual-dialog]')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('[data-visual-dialog-footer]')).toBeVisible()
  await page.waitForTimeout(350)
  const dialogBounds = await dialog.boundingBox()
  expect(dialogBounds).not.toBeNull()
  expect(dialogBounds!.x).toBeGreaterThanOrEqual(0)
  expect(dialogBounds!.x + dialogBounds!.width).toBeLessThanOrEqual(viewport.width)
  await dialog.locator('[data-visual-dialog-footer] button').first().click()
  await expect(dialog).toBeHidden()
})

test('语言、主题和窗口尺寸变化触发安全重排', async ({ page }, testInfo) => {
  const variant = await openMatrix(page, testInfo.project.name)
  const initialResizeCount = Number(await page.locator('[data-resize-count]').textContent().then((text) => text?.match(/\d+$/)?.[0] ?? '0'))

  await page.locator('[data-visual-locale-toggle]').click()
  await expect(page.locator('html')).toHaveAttribute('data-visual-locale', variant.locale === 'en' ? 'zh-CN' : 'en')
  await expect(page.locator('[data-visual-page="job-center"] h2')).toHaveText(variant.locale === 'en' ? '任务中心' : 'Job Center')

  await page.locator('[data-visual-theme-toggle]').click()
  await expect(page.locator('html')).toHaveAttribute('data-visual-theme', variant.theme === 'dark' ? 'light' : 'dark')
  await expectAppliedTheme(page, variant.theme === 'dark' ? 'light' : 'dark')
  await expect(page.locator('[data-visual-chart]').first()).toBeVisible()

  const viewport = page.viewportSize()!
  await page.setViewportSize({ width: Math.max(960, viewport.width - 80), height: Math.max(600, viewport.height - 20) })
  await expect.poll(async () => Number(await page.locator('[data-resize-count]').textContent().then((text) => text?.match(/\d+$/)?.[0] ?? '0'))).toBeGreaterThan(initialResizeCount)
  const chartBounds = await page.locator('[data-visual-chart]').first().boundingBox()
  expect(chartBounds).not.toBeNull()
  expect(chartBounds!.width).toBeGreaterThan(0)
  expect(chartBounds!.height).toBeGreaterThan(0)
})

test('矩阵组合生成稳定补充截图', async ({ page }, testInfo) => {
  await openMatrix(page, testInfo.project.name)
  await expect(page.locator('[data-visual-chart]').first()).toBeVisible()
  await expect(page.locator('[data-visual-sidebar]')).toBeVisible()
  const screenshot = await page.screenshot({ path: testInfo.outputPath('visual-matrix-shell.png'), fullPage: true })
  expect(screenshot.byteLength).toBeGreaterThan(1_000)
})
