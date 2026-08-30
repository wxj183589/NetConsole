import { expect, test, type Page } from '@playwright/test'

const activeSite = {
  site_id: 'line-10',
  display_name: '杭州地铁10号线',
  line_name: '杭州地铁10号线',
  project_type: 'PIS车地无线系统',
  path: 'D:\\study\\NetConsole-Workspace\\test-data\\NetConsole\\visual\\sites\\line-10',
  created_at: '2026-08-01T09:00:00',
  updated_at: '2026-08-06T09:00:00',
  remark: '',
  active: true,
  size_bytes: 620_022_579,
  site_kind: 'formal',
  classification: 'normal_site',
  managed_demo: false,
  demo_seed_version: '',
  migration_status: 'current',
  data_integrity: 'unknown',
  recommended_action: 'keep_and_review',
  audited_at: '2026-08-06T08:30:00',
}

const legacySite = {
  ...activeSite,
  site_id: 'legacy-line-2',
  display_name: '历史二号线局点',
  line_name: null,
  project_type: null,
  path: 'D:\\study\\NetConsole-Workspace\\test-data\\NetConsole\\visual\\sites\\历史二号线局点',
  active: false,
  size_bytes: 82_313_420,
  site_kind: 'legacy',
  classification: 'legacy_valid',
  data_integrity: 'ok',
  audited_at: '',
}

async function mockSiteStorage(page: Page): Promise<void> {
  await page.route('**/api/v1/sites', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([activeSite, legacySite]),
  }))
  await page.route('**/api/v1/storage/data-root', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      data_root: 'D:\\study\\NetConsole-Workspace\\test-data\\NetConsole\\visual',
      default_data_root: 'D:\\study\\NetConsole-Workspace\\test-data\\NetConsole\\visual',
      site_count: 2,
      active_site_id: 'line-10',
      storage_mode: 'persistent',
      data_root_kind: 'persistent',
      persistent: true,
    }),
  }))
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockSiteStorage(page)
  await page.goto('/tests/visual/site-storage.html?netconsole_host=electron', {
    waitUntil: 'networkidle',
  })
  await expect(page.getByText('杭州地铁10号线', { exact: true }).first()).toBeVisible()
})

test('桌面布局展示信息标签、完整操作菜单和编辑弹窗', async ({ page }, testInfo) => {
  await expect(page.getByText('线路：杭州地铁10号线')).toBeVisible()
  await expect(page.getByText('项目类型：PIS车地无线系统')).toBeVisible()
  await expect(page.getByText('线路未填写')).toBeVisible()
  await expect(page.getByText('项目类型未填写')).toBeVisible()

  await page.getByTestId('more-site-legacy-line-2').click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('menuitem', { name: '编辑局点信息' })).toBeVisible()
  await expect(menu.getByRole('menuitem', { name: '重命名' })).toBeVisible()
  await expect(menu.getByRole('menuitem', { name: '删除局点' })).toBeVisible()
  await menu.getByRole('menuitem', { name: '编辑局点信息' }).click()
  await expect(menu).toBeHidden()

  const dialog = page.getByRole('dialog', { name: '编辑局点信息' })
  await expect(dialog).toBeVisible()
  await page.waitForTimeout(350)
  const dialogBounds = await dialog.boundingBox()
  expect(dialogBounds).not.toBeNull()
  expect(dialogBounds!.x).toBeGreaterThanOrEqual(0)
  expect(dialogBounds!.x + dialogBounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  const screenshot = await page.screenshot({
    path: testInfo.outputPath('site-storage-desktop.png'),
    fullPage: true,
  })
  expect(screenshot.byteLength).toBeGreaterThan(1_000)
})

test('窄视口无横向溢出且删除确认必须精确输入名称', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 540, height: 760 })
  await page.reload({ waitUntil: 'networkidle' })
  const panel = page.locator('.storage-panel')
  await expect(panel).toBeVisible()
  const layout = await panel.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }))
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1)

  await page.getByTestId('more-site-legacy-line-2').click()
  await page.getByRole('menuitem', { name: '删除局点' }).click()
  const dialog = page.getByRole('dialog', { name: '删除局点' })
  await expect(dialog).toBeVisible()
  await page.waitForTimeout(350)
  await expect(dialog.getByText('legacy-line-2')).toBeVisible()
  await expect(dialog.getByText('78.5 MB')).toBeVisible()
  const confirm = dialog.getByRole('button', { name: '移入 .trash' })
  const input = dialog.getByTestId('nc-confirm-typed-input')
  await expect(confirm).toBeDisabled()
  await input.fill('历史二号线')
  await expect(confirm).toBeDisabled()
  await input.fill('历史二号线局点')
  await expect(confirm).toBeEnabled()

  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(540)
  const screenshot = await page.screenshot({
    path: testInfo.outputPath('site-storage-narrow-delete.png'),
    fullPage: true,
  })
  expect(screenshot.byteLength).toBeGreaterThan(1_000)
})
