import { describe, expect, it } from 'vitest'
import { readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import html from '../../index.html?raw'
import layout from '../layouts/AppLayout.vue?raw'
import dashboard from '../views/DashboardView.vue?raw'

describe('desktop renderer product copy', () => {
  it('uses the branded title, favicon, and sidebar logo without internal migration labels', () => {
    expect(html).toContain('<title>NetConsole v1.4.4 by wxj</title>')
    expect(html).toContain('<link rel="icon" type="image/png" href="/branding/netconsole.png" />')
    expect(layout).toContain('class="brand-logo"')
    expect(layout).toContain("const BRAND_LOGO_URL = '/branding/netconsole.png'")
    expect(layout).toContain(':src="BRAND_LOGO_URL"')
    expect(layout).toContain('alt="NetConsole"')
    expect(layout).not.toMatch(/>\s*NC\s*</)
    expect(dashboard).toContain('当前版本功能状态')
    expect(dashboard).toContain('查看命令说明')
    expect(layout).toContain('本地网络运维控制台')
    expect(`${html}${layout}${dashboard}`).not.toContain('Electron + Qt 并行迁移')
    expect(`${html}${layout}${dashboard}`).not.toContain('NetConsole Web</')
  })

  it('keeps web branding resources available to Vite public assets', () => {
    for (const file of ['netconsole.png', 'netconsole.ico']) {
      const path = fileURLToPath(new URL(`../../public/branding/${file}`, import.meta.url))
      expect(statSync(path).size).toBeGreaterThan(0)
      expect(readFileSync(path).length).toBeGreaterThan(0)
    }
  })
})
