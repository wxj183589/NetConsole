import { describe, expect, it } from 'vitest'

import html from '../../index.html?raw'
import layout from '../layouts/AppLayout.vue?raw'
import dashboard from '../views/DashboardView.vue?raw'

describe('desktop renderer product copy', () => {
  it('uses the NetConsole title without internal migration labels', () => {
    expect(html).toContain('<title>NetConsole</title>')
    expect(dashboard).toContain('当前版本功能状态')
    expect(dashboard).toContain('查看命令说明')
    expect(layout).toContain('本地网络运维控制台')
    expect(`${html}${layout}${dashboard}`).not.toContain('Electron + Qt 并行迁移')
    expect(`${html}${layout}${dashboard}`).not.toContain('NetConsole Web</')
  })
})
